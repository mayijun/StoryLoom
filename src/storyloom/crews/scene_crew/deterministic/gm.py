"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

GM GameMaster：Crew 的 Deterministic Agent，把「想做什么」变成「能不能发生」。

GM 从 world/game_master.py 迁入此处，成为 Crew 协作单元的一员。
它是纯代码裁决器，不调用 LLM，不受模型质量波动影响。

纪律：
- LLM Agents 只出提案，GM 用 WorldState 复核；
- 时间、随机、算术、配额都在代码层确定性完成；
- 规则缺口按 gap_policy 处理：reject | llm_referee | human_review。

ActionProposal / AdjudicationResult 是 Layer 0 公共协议，
已迁至 storyloom.world.state，这里从那里 import。
"""

from typing import Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from storyloom.world.state import (
    ActionProposal,
    AdjudicationResult,
    CharState,
    Fact,
    StateDelta,
    WorldEvent,
    WorldState,
)

GUARD_KEYWORDS = ("护卫", "侍卫", "卫兵", "守卫", "骑士", "guard")
PRISON_LOCATION = "地牢"


class GameMaster:
    """Crew 的确定性世界裁决 Agent"""

    def __init__(
        self,
        gap_policy: Literal["reject", "llm_referee", "human_review"] = "reject",
        referee: Optional[
            Callable[[ActionProposal, WorldState], Optional[AdjudicationResult]]
        ] = None,
        travel_overrides: Optional[Dict[str, int]] = None,
    ):
        self.gap_policy = gap_policy
        self.referee = referee
        # key: "起点->终点"，由 map mod 注入的旅行耗时覆盖
        self.travel_overrides = dict(travel_overrides or {})

    # ---------------- 查询 ----------------

    def resolve_location(
        self, state: WorldState, name: str
    ) -> Optional[str]:
        """把玩家说法解析为地图里的地点名（支持子串匹配）"""
        if not name:
            return None
        if name in state.locations:
            return name
        for candidate in state.locations:
            if name in candidate or candidate in name:
                return candidate
        return None

    def travel_minutes(
        self, state: WorldState, origin: str, destination: str
    ) -> Optional[int]:
        override = self.travel_overrides.get(f"{origin}->{destination}")
        if override is not None:
            return override
        loc = state.locations.get(origin)
        if loc and destination in loc.exits:
            return loc.exits[destination]
        return None

    def allowed_actions(
        self, state: WorldState, actor: str
    ) -> List[Dict[str, str]]:
        """地点 + 在场角色 → 可用行动列表（委托给 WorldState）"""
        return state.allowed_actions(actor)

    # ---------------- 裁决 ----------------

    def adjudicate(
        self, proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        actor = state.characters.get(proposal.actor)
        if actor is None:
            return AdjudicationResult(
                success=False,
                outcome="rejected",
                error_code="actor_not_found",
                narrative=f"不存在的行动者：{proposal.actor}",
                rule="existence",
            )

        if actor.status == "dead":
            return AdjudicationResult(
                success=False,
                outcome="rejected",
                error_code="actor_dead",
                narrative="你已经无法行动。",
                rule="existence",
            )

        handlers = {
            "move": self._move,
            "attack": self._attack,
            "talk": self._talk,
            "wait": self._wait,
            "observe": self._observe,
            "use": self._use,
        }
        handler = handlers.get(proposal.kind)
        if handler is None:
            return self._resolve_gap(proposal, state)
        return handler(proposal, state)

    # ---------------- 各行动 ----------------

    def _move(
        self, proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        actor = state.characters[proposal.actor]
        dest = self.resolve_location(state, proposal.target or "")
        available = list(
            state.locations.get(actor.location).exits
            if state.locations.get(actor.location)
            else []
        )
        if dest is None:
            return AdjudicationResult(
                success=False,
                outcome="not_found",
                error_code="not_found",
                narrative=(
                    f"「{proposal.target or '那里'}」并不在你的世界地图上。"
                ),
                available=available,
                rule="existence",
            )
        if dest == actor.location:
            return AdjudicationResult(
                success=False,
                outcome="noop",
                narrative=f"你已经在{dest}了。",
                available=available,
                rule="presence",
            )

        travel = self.travel_minutes(state, actor.location, dest)
        if travel is None:
            # 地点存在但不可直达：A2 要求返回 not_found + 可去地点
            return AdjudicationResult(
                success=False,
                outcome="not_found",
                error_code="not_found",
                narrative=(
                    f"你无法从{actor.location}直接到{dest}。"
                ),
                available=available,
                rule="reachability",
            )

        origin = actor.location
        delta = StateDelta(
            time_delta=travel,
            characters={
                proposal.actor: {
                    "location": dest,
                    "status": "active",
                    "emotion": "警觉",
                }
            },
            events=[
                state.touch(
                    "move",
                    proposal.actor,
                    f"{proposal.actor}从{origin}移动到{dest}（{travel}分钟）",
                    origin=origin,
                    destination=dest,
                )
            ],
        )
        return AdjudicationResult(
            success=True,
            outcome="moved",
            narrative=(
                f"你从{origin}前往{dest}，路上花了{travel}分钟。"
            ),
            state_delta=delta,
            available=list(
                state.locations.get(dest).exits
                if state.locations.get(dest)
                else []
            ),
            rule="travel_time",
        )

    def _attack(
        self, proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        actor = state.characters[proposal.actor]
        target_name = proposal.target or ""
        target = state.characters.get(target_name)
        if target is None:
            return AdjudicationResult(
                success=False,
                outcome="not_found",
                error_code="target_not_found",
                narrative=(
                    f"没有找到目标：{target_name}"
                    if target_name
                    else "你想出手，但身边没有可攻击的目标。"
                ),
                rule="existence",
            )
        if target.location != actor.location or target.status != "active":
            return AdjudicationResult(
                success=False,
                outcome="not_present",
                error_code="not_present",
                narrative=f"{target_name}并不在这里。",
                rule="presence",
            )

        guards = [
            name
            for name in state.characters_at(actor.location)
            if name != proposal.actor
            and name != target_name
            and any(k in name for k in GUARD_KEYWORDS)
        ]
        if guards:
            prison = self.resolve_location(state, PRISON_LOCATION)
            char_patch: Dict[str, object] = {
                "emotion": "恐惧",
                "status": "imprisoned" if prison is None else "active",
            }
            if prison:
                char_patch["location"] = prison
            delta = StateDelta(
                time_delta=5,
                characters={proposal.actor: char_patch},
                flags={"imprisoned_by": guards[0]},
                events=[
                    state.touch(
                        "attack",
                        proposal.actor,
                        f"{proposal.actor}袭击{target_name}，被{guards[0]}当场制止",
                        target=target_name,
                        guards=guards,
                    )
                ],
            )
            where = prison or actor.location
            return AdjudicationResult(
                success=False,
                outcome="intercepted",
                error_code="blocked_by_guard",
                narrative=(
                    f"你刚拔出武器，{guards[0]}已经挡在{target_name}身前。"
                    f"你被制服并押往{where}。"
                ),
                state_delta=delta,
                rule="guard_intercept",
            )

        delta = StateDelta(
            time_delta=1,
            characters={
                target_name: {"health": 0, "status": "dead"},
                proposal.actor: {"emotion": "激动"},
            },
            flags={f"attacked:{target_name}": True},
            events=[
                state.touch(
                    "attack",
                    proposal.actor,
                    f"{proposal.actor}攻击了{target_name}",
                    target=target_name,
                )
            ],
        )
        return AdjudicationResult(
            success=True,
            outcome="hit",
            narrative=f"你击倒了{target_name}。",
            state_delta=delta,
            rule="attack_no_guard",
        )

    def _talk(
        self, proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        actor = state.characters[proposal.actor]
        target_name = proposal.target or ""
        target = state.characters.get(target_name)
        if target is None or target.location != actor.location:
            return AdjudicationResult(
                success=False,
                outcome="not_present",
                error_code="not_present",
                narrative=f"{target_name or '那个人'}并不在这里。",
                rule="presence",
            )
        key = "|".join(sorted([proposal.actor, target_name]))
        value = state.relationships.get(key, 0) + 1
        delta = StateDelta(
            time_delta=3,
            relationships={key: value},
            characters={proposal.actor: {"emotion": "放松"}},
            events=[
                state.touch(
                    "talk",
                    proposal.actor,
                    f"{proposal.actor}与{target_name}交谈",
                    target=target_name,
                )
            ],
        )
        return AdjudicationResult(
            success=True,
            outcome="talked",
            narrative=(
                f"你和{target_name}交换了几句话。"
                if proposal.actor == "玩家"
                else f"{proposal.actor}和{target_name}交换了几句话。"
            ),
            state_delta=delta,
            rule="social",
        )

    def _wait(
        self, proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        minutes = int(proposal.params.get("minutes", 10))
        delta = StateDelta(
            time_delta=minutes,
            events=[
                state.touch(
                    "wait",
                    proposal.actor,
                    f"{proposal.actor}原地等待了{minutes}分钟",
                )
            ],
        )
        return AdjudicationResult(
            success=True,
            outcome="waited",
            narrative=f"你等了{minutes}分钟。",
            state_delta=delta,
            rule="time",
        )

    def _observe(
        self, proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        actor = state.characters[proposal.actor]
        present = [
            n for n in state.characters_at(actor.location)
            if n != proposal.actor
        ]
        names = "、".join(present) if present else "没有别人"
        return AdjudicationResult(
            success=True,
            outcome="observed",
            narrative=f"你环顾四周，看见{names}。",
            rule="visibility",
        )

    def _use(
        self, proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        # M0 只做确定性提示；具体道具效果由 mod / 后续版本提供
        return AdjudicationResult(
            success=True,
            outcome="used",
            narrative=f"你使用了{proposal.target or '手边的东西'}，暂时没有特别的变化。",
            rule="item",
        )

    # ---------------- 规则缺口 ----------------

    def _resolve_gap(
        self, proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        if self.gap_policy == "llm_referee" and self.referee is not None:
            result = self.referee(proposal, state)
            if result is not None:
                return result
        if self.gap_policy == "human_review":
            return AdjudicationResult(
                success=False,
                outcome="human_review",
                error_code="human_review_required",
                narrative="这个行动需要人工确认后才能继续。",
                quality_flag="human_review",
                rule="gap_policy",
            )
        return AdjudicationResult(
            success=False,
            outcome="rejected",
            error_code="unknown_action",
            narrative="这个行动在这个世界里无法成立。",
            quality_flag="rejected",
            rule="gap_policy",
        )

    # ---------------- 工具 ----------------

    @staticmethod
    def fact_for(
        subject: str,
        predicate: str,
        obj: str,
        known_by: Optional[List[str]] = None,
        source_event: str = "",
    ) -> Fact:
        return Fact(
            subject=subject,
            predicate=predicate,
            object=obj,
            known_by=set(known_by or ["gm"]),
            source_event=source_event,
        )

    @staticmethod
    def event_to_delta(event: WorldEvent) -> StateDelta:
        return StateDelta(events=[event])
