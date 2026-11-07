"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

双模式 TurnLoop：游戏 / 扮演与导演模式共用同一套世界状态与渲染链。

    boot → perceive → classify_input → interpret_*
         → director_frame → actor_round → adjudicate
         → consistency_check → moderation_gate
         → render_scene → commit → plan_next

纪律：
- 全部 async，支持 max_duration_ms 超时与 max_turns / max_retries / max_cost 配额；
- 状态只经 GM / Authority 写入；
- 质量下降不阻塞玩家，打质量标记继续；
- 日志携带 instance_id / work_id / turn_id / trace_id。
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from storyloom.extensions.host import ExtensionHost, ExtensionRegistry
from storyloom.memory.core import LayeredMemory
from storyloom.models import NovelProject
from storyloom.narrative.arc import ArcDirector, DirectorFrame
from storyloom.runtime.directive import StageScene
from storyloom.runtime.intent import (
    InterpretedIntent,
    IntentRouter,
    PlayerIntent,
)
from storyloom.runtime.renderer import SceneRenderer
from storyloom.saves.service import SaveService
from storyloom.world.autonomous_agent import autonomous_tick
from storyloom.world.authority import (
    AuthorityController,
    DirectorAuthority,
    FactOverride,
    GameAuthority,
)
from storyloom.world.game_master import (
    ActionProposal,
    AdjudicationResult,
    GameMaster,
)
from storyloom.world.state import StateDelta, WorldState


class TurnBoot(BaseModel):
    """一次回合启动参数（可由 API 请求体直接反序列化）"""

    project_id: str = ""
    instance_id: str = "default"
    actor: str = "玩家"
    mode: Literal["game", "director"] = "game"
    intent: PlayerIntent = Field(default_factory=PlayerIntent)
    world_state: Optional[WorldState] = None

    max_turns: int = 1
    max_retries: int = 1
    max_cost: float = 1.0
    max_duration_ms: int = 30000

    enabled_extensions: Optional[List[str]] = None
    memory_backend: Optional[Literal["fts", "vector", "hybrid"]] = None
    idle_turns: int = 0
    switch_mode_to: Optional[Literal["game", "director"]] = None
    overrides: List[FactOverride] = Field(default_factory=list)
    goal: str = ""
    # 仅存在运行时内存，不落盘、不写环境变量、不进入日志
    provider_api_keys: Dict[str, str] = Field(default_factory=dict, exclude=True)


class TurnResult(BaseModel):
    """一次回合的完整返回"""

    turn_id: str
    trace_id: str
    project_id: str
    instance_id: str
    status: Literal[
        "ok", "rejected", "idle", "timeout",
        "human_review", "quota_exceeded", "error",
    ] = "ok"
    exit: Literal[
        "next_turn", "stop", "idle_stop", "end_arc", "human_review"
    ] = "next_turn"

    state: WorldState
    state_delta: StateDelta
    scene: StageScene
    text: str = ""
    choices: List[Dict[str, Any]] = Field(default_factory=list)
    quality: float = 1.0
    quality_flags: List[str] = Field(default_factory=list)
    frame: Optional[DirectorFrame] = None
    log: Dict[str, Any] = Field(default_factory=dict)


def merge_deltas(target: StateDelta, patch: StateDelta) -> StateDelta:
    target.time_delta += patch.time_delta
    for name, fields in patch.characters.items():
        target.characters.setdefault(name, {}).update(fields)
    for name, fields in patch.locations.items():
        target.locations.setdefault(name, {}).update(fields)
    target.facts_set.extend(patch.facts_set)
    target.facts_remove.extend(patch.facts_remove)
    target.flags.update(patch.flags)
    target.relationships.update(patch.relationships)
    target.arc.update(patch.arc)
    target.events.extend(patch.events)
    target.promises_set.extend(patch.promises_set)
    target.promises_remove.extend(patch.promises_remove)
    return target


class TurnLoop:
    """双模式回合循环"""

    def __init__(
        self,
        project: NovelProject,
        instance_id: str = "default",
        memory: Optional[LayeredMemory] = None,
        extensions: Optional[ExtensionRegistry] = None,
        save_service: Optional[SaveService] = None,
        renderer: Optional[SceneRenderer] = None,
        gap_policy: str = "reject",
    ):
        self.project = project
        self.instance_id = instance_id
        self.memory = memory
        self.extensions = extensions
        self.save_service = save_service
        self.renderer = renderer or SceneRenderer()
        self.gap_policy = gap_policy
        self.router = IntentRouter()
        self.arc_director = ArcDirector()
        self._rrf_counter = 0

    # ---------------- 入口 ----------------

    async def run(self, boot: TurnBoot) -> TurnResult:
        turn_id = f"turn_{uuid.uuid4().hex[:10]}"
        trace_id = f"trace_{uuid.uuid4().hex[:10]}"
        started = time.perf_counter()
        trace: List[Dict[str, Any]] = []

        state = self._prepare_state(boot, trace)
        if boot.max_turns < 1 or boot.max_cost <= 0:
            return TurnResult(
                turn_id=turn_id,
                trace_id=trace_id,
                project_id=self.project.project_id,
                instance_id=boot.instance_id,
                status="quota_exceeded",
                state=state,
                state_delta=StateDelta(),
                scene=StageScene(),
                quality=0.0,
                quality_flags=["quota_exceeded"],
                log={"trace": trace, "instance_id": boot.instance_id},
            )

        timeout = max(0.001, boot.max_duration_ms / 1000)
        try:
            result = await asyncio.wait_for(
                self._pipeline(boot, state, turn_id, trace_id, trace, started),
                timeout=timeout,
            )
            return result
        except asyncio.TimeoutError:
            trace.append(
                {"stage": "timeout", "elapsed_ms": _ms(started)}
            )
            return TurnResult(
                turn_id=turn_id,
                trace_id=trace_id,
                project_id=self.project.project_id,
                instance_id=boot.instance_id,
                status="timeout",
                exit="stop",
                state=state,
                state_delta=StateDelta(),
                scene=StageScene(),
                quality=0.0,
                quality_flags=["timeout"],
                log={
                    "instance_id": boot.instance_id,
                    "work_id": self.project.project_id,
                    "turn_id": turn_id,
                    "trace_id": trace_id,
                    "trace": trace,
                    "elapsed_ms": _ms(started),
                },
            )

    # ---------------- 准备 ----------------

    def _prepare_state(
        self, boot: TurnBoot, trace: List[Dict[str, Any]]
    ) -> WorldState:
        host = self._host(boot)
        state = boot.world_state or WorldState.from_project(
            self.project, mode=boot.mode
        )
        if boot.mode != state.mode:
            state = state.model_copy(update={"mode": boot.mode})
        state = host.apply_map(state)

        if boot.switch_mode_to:
            controller = self._authority(host)
            state, checkpoint_id = controller.switch_mode(
                state,
                boot.switch_mode_to,
                checkpoint_fn=self._checkpoint_fn(),
                label=f"switch_to_{boot.switch_mode_to}",
            )
            trace.append(
                {"stage": "switch_mode", "checkpoint": checkpoint_id}
            )
        return state

    def _host(self, boot: TurnBoot) -> ExtensionHost:
        if self.extensions is None:
            return ExtensionHost(boot.instance_id, [])
        return self.extensions.for_instance(
            boot.instance_id, enabled=boot.enabled_extensions
        )

    def _authority(self, host: ExtensionHost) -> AuthorityController:
        gm = GameMaster(
            gap_policy=self.gap_policy,  # type: ignore[arg-type]
            travel_overrides=host.travel_overrides(),
        )
        return AuthorityController(GameAuthority(gm), DirectorAuthority(gm))

    def _checkpoint_fn(self):
        def checkpoint(world: WorldState, label: str) -> str:
            if self.save_service is None:
                return ""
            record = self.save_service.save(
                self.project.project_id, world, StageScene(), label=label
            )
            return record.save_id
        return checkpoint

    # ---------------- 主流水线 ----------------

    async def _pipeline(
        self,
        boot: TurnBoot,
        state: WorldState,
        turn_id: str,
        trace_id: str,
        trace: List[Dict[str, Any]],
        started: float,
    ) -> TurnResult:
        host = self._host(boot)
        controller = self._authority(host)
        actor = boot.actor
        before = state

        # 1. perceive
        actor_state = state.characters.get(actor)
        location = actor_state.location if actor_state else ""
        present = state.characters_at(location)
        if self.memory is not None:
            self.memory.configure_working(
                location=location,
                present_characters=present,
                scene_brief=boot.intent.payload.get("text", "")  # type: ignore[union-attr]
                if isinstance(boot.intent.payload, dict) else "",
                intent=boot.intent.kind,
                time=state.format_time(),
            )
        trace.append({"stage": "perceive", "location": location})

        # 2-3. classify + interpret
        interpreted = self.router.route(boot.intent, state, actor)
        trace.append(
            {
                "stage": "classify_input",
                "mode": interpreted.mode,
                "proposals": [p.kind for p in interpreted.proposals],
            }
        )

        overrides_applied: List[FactOverride] = []
        if boot.mode == "director" and boot.overrides:
            authority = controller.director
            for override in boot.overrides:
                snapshot_id = ""
                if self.save_service is not None:
                    snapshot_id = self.save_service.save(
                        self.project.project_id, state, StageScene(),
                        label=f"before_override_{override.override_id}",
                    ).save_id
                state, record = authority.apply_override(
                    override, state, snapshot_id=snapshot_id
                )
                overrides_applied.append(record)
            trace.append(
                {"stage": "interpret_director", "overrides": len(overrides_applied)}
            )

        # 4. director_frame
        frame = self.arc_director.frame(
            state, goal=boot.goal or interpreted.scene_goal
        )
        if state.flags.get("force_director_frame"):
            state = state.model_copy(deep=True)
            state.flags["force_director_frame"] = False
        trace.append({"stage": "director_frame", "phase": frame.phase})

        # 5. actor_round
        proposals = list(interpreted.proposals)
        npc_actors: List[str] = []
        if not proposals and boot.idle_turns >= 3:
            npc_proposals, npc_actors = autonomous_tick(
                state, memory=self.memory, idle_turns=boot.idle_turns
            )
            proposals.extend(npc_proposals)
        trace.append(
            {
                "stage": "actor_round",
                "proposals": len(proposals),
                "npc": npc_actors,
            }
        )

        # 6-7. adjudicate + consistency_check（retry ≤ max_retries）
        retry_count = 0
        results: List[AdjudicationResult] = []
        combined = StateDelta()
        working_state = state
        issues: List[str] = []

        while True:
            working_state, combined, results = self._adjudicate(
                proposals, state, controller, actor, frame
            )
            issues = self._consistency_check(before, working_state)
            if not issues or retry_count >= boot.max_retries:
                break
            retry_count += 1

        working_state = working_state.model_copy(
            update={"turn": before.turn + 1}
        )
        trace.append(
            {
                "stage": "adjudicate",
                "results": [r.outcome for r in results],
                "retries": retry_count,
                "issues": issues,
            }
        )

        # 8. moderation_gate（M0 默认 passthrough）
        quality_flags = self._quality_flags(results, issues, retry_count)

        # 9. render_scene
        primary = results[0] if results else AdjudicationResult(
            success=True, outcome="idle", narrative="你静静地站着，等待下一刻。"
        )
        scene = await self.renderer.arender(
            before, working_state, primary, actor
        )
        trace.append({"stage": "render_scene", "chars": len(scene.text)})

        # 10. commit（内存分层记忆 + arc）
        if self.memory is not None and scene.text:
            self.memory.add_scene(
                scene_index=working_state.turn,
                prose=scene.text,
                brief=str(boot.intent.payload.get("text", "")),
                present_characters=working_state.characters_at(
                    (working_state.characters.get(actor).location
                     if working_state.characters.get(actor) else "")
                ),
            )
        arc = self.arc_director.advance(
            working_state,
            success=any(r.success for r in results),
            dramatic=any(r.outcome in ("hit", "intercepted") for r in results),
        )
        working_state = working_state.model_copy(update={"arc": arc})

        # 11. plan_next
        status, exit_reason = self._plan_next(
            interpreted, results, issues, working_state
        )
        quality = self._quality(results, issues, retry_count)

        trace.append(
            {
                "stage": "plan_next",
                "status": status,
                "exit": exit_reason,
                "elapsed_ms": _ms(started),
            }
        )

        return TurnResult(
            turn_id=turn_id,
            trace_id=trace_id,
            project_id=self.project.project_id,
            instance_id=boot.instance_id,
            status=status,
            exit=exit_reason,
            state=working_state,
            state_delta=combined,
            scene=scene,
            text=scene.text,
            choices=scene.choices,
            quality=quality,
            quality_flags=quality_flags,
            frame=frame,
            log={
                "instance_id": boot.instance_id,
                "work_id": self.project.project_id,
                "turn_id": turn_id,
                "trace_id": trace_id,
                "trace": trace,
                "retry_count": retry_count,
                "overrides": [o.model_dump(mode="json") for o in overrides_applied],
                "elapsed_ms": _ms(started),
            },
        )

    # ---------------- 各阶段实现 ----------------

    def _adjudicate(
        self,
        proposals: List[ActionProposal],
        state: WorldState,
        controller: AuthorityController,
        actor: str,
        frame: DirectorFrame,
    ) -> Tuple[WorldState, StateDelta, List[AdjudicationResult]]:
        working = state
        combined = StateDelta()
        results: List[AdjudicationResult] = []
        policy = controller.policy_for(working.mode)

        for proposal in proposals:
            if proposal.actor != actor and proposal.source != "npc":
                proposal = proposal.model_copy(update={"actor": actor})
            result = policy.adjudicate(proposal, working, frame)
            working = working.apply_delta(
                result.state_delta, advance_turn=False
            )
            combined = merge_deltas(combined, result.state_delta)
            results.append(result)
        return working, combined, results

    @staticmethod
    def _consistency_check(
        before: WorldState, after: WorldState
    ) -> List[str]:
        issues: List[str] = []
        if after.time_minutes < before.time_minutes:
            issues.append("世界时间倒退")
        for name, char in after.characters.items():
            if char.location not in after.locations:
                issues.append(f"{name}的位置不存在：{char.location}")
            if char.health < 0:
                issues.append(f"{name}的生命值非法")
        return issues

    def _quality_flags(
        self,
        results: List[AdjudicationResult],
        issues: List[str],
        retry_count: int,
    ) -> List[str]:
        flags: List[str] = []
        if retry_count:
            flags.append(f"retry:{retry_count}")
        if issues:
            flags.extend(f"issue:{item}" for item in issues)
        for result in results:
            if result.quality_flag:
                flags.append(result.quality_flag)
        return flags

    @staticmethod
    def _quality(
        results: List[AdjudicationResult],
        issues: List[str],
        retry_count: int,
    ) -> float:
        if issues:
            return 0.4
        quality = 1.0
        for result in results:
            if not result.success:
                quality -= 0.15
        quality -= 0.1 * retry_count
        return max(0.0, round(quality, 2))

    @staticmethod
    def _plan_next(
        interpreted: InterpretedIntent,
        results: List[AdjudicationResult],
        issues: List[str],
        state: WorldState,
    ) -> Tuple[str, str]:
        if any(r.outcome == "human_review" for r in results):
            return "human_review", "human_review"
        if issues:
            return "rejected", "stop"
        if not results:
            return "idle", "idle_stop"
        if state.arc.phase == "resolution" and state.arc.beats_remaining <= 1:
            return "ok", "end_arc"
        if interpreted.mode == "meta":
            return "ok", "stop"
        return "ok", "next_turn"


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


__all__ = [
    "TurnBoot",
    "TurnLoop",
    "TurnResult",
    "merge_deltas",
]
