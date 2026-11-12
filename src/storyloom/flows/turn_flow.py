"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

双模式 TurnLoop：游戏 / 扮演与导演模式共用同一套世界状态与 SceneCrew 多 Agent 链。

    boot → perceive → freeform_input
         → director_frame → actor_round → adjudicate
         → [scene_crew_narrative]  ← SceneCrew: Surprise + Foreshadow + Director +
         → consistency_check           Consistency + Prose
         → moderation_gate
         → render_scene → commit → plan_next

SceneCrew 策略（避免每回合都跑全套 agent 的成本）：
- 游戏模式：每回合跑 Consistency + Prose；每 3~5 回合抽样触发 Surprise + Foreshadow + Director
- 导演模式：每回合全跑（Surprise + Foreshadow + Director + Consistency + Prose）
- crew=None：退回原简化路径（硬编码一致性 + narrator 单模型润色），兼容旧测试

纪律：
- 全部 async，支持 max_duration_ms 超时与 max_turns / max_retries / max_cost 配额；
- 状态只经 GM / Authority 写入；SceneCrew 只产出叙事层文本，不修改 WorldState；
- 质量下降不阻塞玩家，打质量标记继续；
- 日志携带 instance_id / work_id / turn_id / trace_id。
"""

import asyncio
import time
import uuid
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from storyloom.crews.scene_crew.crew import SceneCrew
from storyloom.crews.scene_crew.packet import (
    AgentPacket,
    compose_scene,
    parse_agent_packet,
)
from storyloom.extensions.host import ExtensionHost, ExtensionRegistry
from storyloom.memory.checkpoint import SaveService
from storyloom.memory.core import LayeredMemory
from storyloom.memory.models import NovelProject
from storyloom.crews.scene_crew.arc import ArcDirector, DirectorFrame
from storyloom.memory.state import (
    ActionProposal,
    AdjudicationResult,
    FactOverride,
    StageScene,
    StateDelta,
    WorldState,
)


class TurnBoot(BaseModel):
    """一次回合启动参数（可由 API 请求体直接反序列化）"""

    project_id: str = ""
    instance_id: str = "default"
    actor: str = "玩家"
    mode: Literal["game", "director"] = "game"
    text: str = ""
    wait: bool = False
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


def parse_narrative_output(raw: str) -> AgentPacket:
    """兼容旧名：解析统一 Agent JSON 信封。"""
    return parse_agent_packet(raw)


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
    """双模式回合循环（可选集成 SceneCrew 多 Agent 链）

    crew 为 None 时退回原简化路径，保证旧测试通过。
    传入后游戏模式与导演模式共用同一套 SceneCrew 的叙事能力。
    """

    def __init__(
        self,
        project: NovelProject,
        instance_id: str = "default",
        memory: Optional[LayeredMemory] = None,
        extensions: Optional[ExtensionRegistry] = None,
        save_service: Optional[SaveService] = None,
        prose_fn: Optional[Callable[[str, WorldState], str]] = None,
        crew: Optional[SceneCrew] = None,
    ):
        self.project = project
        self.instance_id = instance_id
        self.memory = memory
        self.extensions = extensions
        self.save_service = save_service
        # crew 不可用时的确定性正文兜底（engine 注入模型润色函数）
        self.prose_fn = prose_fn
        self.arc_director = ArcDirector()
        self._rrf_counter = 0
        self.crew = crew
        # 用于游戏模式下抽样触发高成本 agent（surprise / foreshadow / director）
        self._crew_turn_counter = 0

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
            checkpoint_id = ""
            if self.save_service is not None:
                checkpoint_id = self.save_service.save(
                    self.project.project_id,
                    state,
                    StageScene(),
                    label=f"switch_to_{boot.switch_mode_to}",
                    kind="checkpoint",
                ).save_id
            state = state.switch_mode(
                boot.switch_mode_to, checkpoint_id=checkpoint_id
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
        actor = boot.actor
        before = state

        # 1. perceive
        actor_state = state.characters.get(actor)
        location = actor_state.location if actor_state else ""
        present = state.characters_at(location)
        action_text = boot.text.strip()
        if self.memory is not None:
            self.memory.configure_working(
                location=location,
                present_characters=present,
                scene_brief=action_text,
                intent=action_text or ("等待" if boot.wait else ""),
                time=state.format_time(),
            )
        trace.append({"stage": "perceive", "location": location})

        # 2-3. 自由文本直接包装为行动，不做关键词分类或动作白名单校验。
        proposals: List[ActionProposal] = []
        if action_text:
            proposals.append(
                ActionProposal(
                    actor=actor,
                    kind="other",
                    detail=action_text,
                    source="player",
                )
            )
        trace.append(
            {
                "stage": "freeform_input",
                "chars": len(action_text),
                "wait": boot.wait,
            }
        )

        overrides_applied: List[FactOverride] = []
        if boot.mode == "director" and boot.overrides:
            for override in boot.overrides:
                snapshot_id = ""
                if self.save_service is not None:
                    snapshot_id = self.save_service.save(
                        self.project.project_id, state, StageScene(),
                        label=f"before_override_{override.override_id}",
                        kind="checkpoint",
                    ).save_id
                state, record = state.apply_override(
                    override, snapshot_id=snapshot_id
                )
                overrides_applied.append(record)
            trace.append(
                {"stage": "interpret_director", "overrides": len(overrides_applied)}
            )

        # 4. director_frame
        frame = self.arc_director.frame(
            state, goal=boot.goal or action_text
        )
        if state.flags.get("force_director_frame"):
            state = state.model_copy(deep=True)
            state.flags["force_director_frame"] = False
        trace.append({"stage": "director_frame", "phase": frame.phase})

        # 5. actor_round
        npc_actors: List[str] = []
        if not proposals and boot.idle_turns >= 3:
            npc_proposals, npc_actors = await self._npc_round(
                state, boot.idle_turns
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
            working_state, combined, results = await self._adjudicate(
                proposals, state, actor, frame, boot.mode
            )
            issues = self._consistency_check(before, working_state)
            # ConsistencyAgent 语义级检测（有 crew 时叠加）
            if self.crew is not None:
                crew_issues = await self.crew.check_consistency(
                    self.project,
                    working_state,
                    before,
                    results,
                    actor,
                    director_mode=(boot.mode == "director"),
                )
                issues.extend(crew_issues)
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

        # 7.5 SceneCrew 叙事增强：Surprise + Foreshadow + Director + Prose（可选）
        crew_narrative = AgentPacket()
        crew_trace: Dict[str, Any] = {}
        if self.crew is not None and any(r.success for r in results):
            self._crew_turn_counter += 1
            crew_narrative, crew_trace = await self._crew_narrative_round(
                boot.mode, working_state, before, results, actor, frame,
                action_text,
            )
            trace.append({"stage": "scene_crew_narrative", **crew_trace})

        # 8. moderation_gate（M0 默认 passthrough）
        quality_flags = self._quality_flags(results, issues, retry_count)
        if crew_trace.get("crew_issues"):
            quality_flags.extend(
                f"crew_issue:{i}" for i in crew_trace["crew_issues"]
            )

        # 9. render_scene（注入分层记忆 + SceneCrew 叙事文本）
        primary = results[0] if results else AdjudicationResult(
            success=True, outcome="idle", narrative="你静静地站着，等待下一刻。"
        )
        memory_context = ""
        if self.memory is not None:
            query = action_text or primary.narrative
            core = self.memory.prompt_block(viewer=actor)
            retrieved = self.memory.retrieval_block(query, viewer=actor)
            memory_context = "\n".join(
                part for part in (core, retrieved) if part
            )
        # crew 叙事文本作为可选的 prose 输入，优先于 prose_fn 兜底
        scene = await self._render_scene(
            before, working_state, primary, actor,
            memory_context, crew_narrative, boot.mode,
        )
        trace.append({"stage": "render_scene", "chars": len(scene.text),
                      "crew_prose": bool(crew_narrative.prose)})

        # 10. commit（内存分层记忆 + arc）
        # 只记录真正推进了世界的回合：被拒绝 / 一致性失败 / 空转的回合不写记忆，
        # 避免无效输入污染短期与正史。
        if (
            self.memory is not None
            and scene.text
            and not issues
            and any(result.success for result in results)
        ):
            self.memory.add_scene(
                scene_index=working_state.turn,
                prose=scene.text,
                brief=action_text,
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
            results, issues, working_state
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

    def _world_context(self, state: WorldState, actor: str) -> str:
        """构造渲染用世界书：以 state.view(actor) 为唯一数据源。

        纪律：
        - 项目元信息（作品名/文风/设定）保留；
        - 运行时状态全部经 view() 过滤，杜绝不在场 NPC 位置、NPC 全量动机、
          GM 内部 flags、NPC-NPC 关系等信息越权泄漏；
        - GM/Director 模式下 view() 自动全知，无需特殊分支。
        """
        project = self.project
        view = state.view(actor)

        lines: List[str] = [f"作品：{project.title}"]
        if project.style:
            lines.append(f"文风：{project.style}")
        if project.description:
            lines.append(f"设定：{project.description}")

        lines.append(
            f"当前节拍：{view['arc']['phase']} / "
            f"张力目标 {view['arc']['tension_target']:.2f} / "
            f"剩余节拍 {view['arc']['beats_remaining']}"
        )
        lines.append(f"世界时间：{view['time']}（第 {view['turn']} 回合）")

        # —— 地点：只列 view 可见（非全知 actor 仅当前地点）——
        if view["locations"]:
            lines.append("地点：")
            for loc in view["locations"]:
                desc = f"：{loc['description']}" if loc.get("description") else ""
                exits = loc.get("exits") or {}
                exit_str = (
                    f"（出口：{', '.join(exits.keys())}）" if exits else ""
                )
                lines.append(f"- {loc['name']}{desc}{exit_str}")

        # —— 角色：只列 view 可见（非全知 actor 仅在场角色）——
        if view["characters"]:
            lines.append("在场角色：")
            for c in view["characters"]:
                emotion = f"，{c['emotion']}" if c.get("emotion") else ""
                lines.append(f"- {c['name']}{emotion}")

        # —— 事实：按 known_by 过滤后的条目 ——
        if view["facts"]:
            lines.append("已知事实：")
            for f in view["facts"]:
                lines.append(
                    f"- {f['subject']} {f['predicate']} {f['object']}"
                )

        # —— 关系：全知 actor 看全部，否则只列 key 含 actor 的 ——
        if state.relationships:
            omniscient = actor in ("gm", "director", "narrator")
            visible = (
                list(state.relationships.items())
                if omniscient
                else [(k, v) for k, v in state.relationships.items() if actor in k]
            )
            if visible:
                lines.append("关系：")
                for k, v in visible:
                    lines.append(f"- {k} = {v}")

        # —— 最近事件 ——
        if view["events"]:
            lines.append("最近发生：")
            for e in view["events"]:
                lines.append(f"- {e['summary']}")

        return "\n".join(lines)

    async def _adjudicate(
        self,
        proposals: List[ActionProposal],
        state: WorldState,
        actor: str,
        frame: DirectorFrame,
        mode: str,
    ) -> Tuple[WorldState, StateDelta, List[AdjudicationResult]]:
        working = state
        combined = StateDelta()
        results: List[AdjudicationResult] = []

        for proposal in proposals:
            if proposal.actor != actor and proposal.source != "npc":
                proposal = proposal.model_copy(update={"actor": actor})
            if self.crew is not None:
                result = await self.crew.adjudicate(
                    proposal, working, mode=mode, frame=frame
                )
            else:
                result = self._fallback_adjudicate(proposal, working)
            working = working.apply_delta(
                result.state_delta, advance_turn=False
            )
            combined = merge_deltas(combined, result.state_delta)
            results.append(result)
        return working, combined, results

    @staticmethod
    def _fallback_adjudicate(
        proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        """无 Crew 时的最小兜底：自由文本直接进入叙事并推进 1 分钟。"""
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
        detail = proposal.detail.strip() or "世界安静地向前推进。"
        return AdjudicationResult(
            success=True,
            outcome="narrated",
            narrative=detail,
            state_delta=StateDelta(
                time_delta=1,
                events=[state.touch("freeform", proposal.actor, detail)],
            ),
            rule="freeform_narrative",
        )

    async def _npc_round(
        self, state: WorldState, idle_turns: int
    ) -> Tuple[List[ActionProposal], List[str]]:
        if self.crew is not None:
            return await self.crew.npc_actions(
                state, idle_turns=idle_turns, memory=self.memory
            )
        if idle_turns < 3:
            return [], []
        player = state.characters.get("玩家")
        location = player.location if player else ""
        candidates = [
            name for name in state.characters_at(location) if name != "玩家"
        ]
        from storyloom.crews.scene_crew.crew import _fallback_npc

        proposals = _fallback_npc(state, candidates[:2])
        return proposals, [item.actor for item in proposals]

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
        return "ok", "next_turn"

    # ---------------- SceneCrew 叙事增强 ----------------

    async def _run_crew_agent(
        self, agent, prompt: str, timeout_s: float = 60.0,
    ) -> Optional[str]:
        """同步 kickoff 的异步包装；LLM 不可用或超时返回 None 让上层兜底

        默认 60 秒足够推理型模型（deepseek-v4-pro / claude-sonnet）返回；
        快模型（flash）一般 5-10 秒。超时不是错误，只是说明叙事增强层本次
        不可用，主流程继续跑 GM + 硬编码一致性 + narrator 单模型。
        """
        loop = asyncio.get_event_loop()

        def _kickoff():
            return agent.kickoff(prompt)

        try:
            output = await asyncio.wait_for(
                loop.run_in_executor(None, _kickoff),
                timeout=timeout_s,
            )
            return str(output.raw).strip() if output else None
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    async def _crew_narrative_round(
        self,
        mode: Literal["game", "director"],
        working_state: WorldState,
        before: WorldState,
        results: List[AdjudicationResult],
        actor: str,
        frame: DirectorFrame,
        action_text: str,
    ) -> Tuple[AgentPacket, Dict[str, Any]]:
        """SceneCrew 叙事层增强（Surprise + Foreshadow + Director + Prose）

        游戏模式：每 3 回合抽样运行 Surprise + Foreshadow + Director（控制成本），
        Prose 每回合都跑；导演模式每回合全跑。
        """
        trace: Dict[str, Any] = {
            "surprise": False, "foreshadow": False, "director": False,
            "prose": False, "mode": mode,
        }
        project = self.project
        primary = results[0] if results else None

        # 构建本回合的场景简报
        present_chars = working_state.characters_at(
            (working_state.characters.get(actor).location
             if working_state.characters.get(actor) else "")
        )
        location = (
            working_state.characters[actor].location
            if actor in working_state.characters else ""
        )
        scene_brief = (
            f"时间: {working_state.format_time()}\n"
            f"地点: {location}\n"
            f"在场: {', '.join(present_chars) if present_chars else '无'}\n"
            f"玩家意图: {action_text or '（空转）'}\n"
            f"GM裁决: {primary.narrative if primary else '无'}"
        )

        # 核心记忆上下文；archive 在 render_scene 前按需检索
        memory_block = ""
        if self.memory is not None:
            memory_block = self.memory.prompt_block(viewer=actor)

        # ---------- 抽样策略 ----------
        run_full = (
            mode == "director"
            or self._crew_turn_counter % 3 == 0  # 游戏模式每 3 回合全跑一次
        )

        # 0. SurpriseAgent
        surprise_text = ""
        if run_full and self.crew is not None:
            cooldown_hint = ""
            scenes_since = (
                project.scene_count - project.last_major_surprise_scene
            )
            if scenes_since < project.surprise_cooldown:
                cooldown_hint = (
                    f"\n⚠️ 距上次重大意外仅过了{scenes_since}个场景，"
                    f"建议本回合只给 minor 级别的小意外。"
                )
            prompt = self.crew.task_prompt(
                "surprise_proposal",
                project_title=project.title,
                memory_block=memory_block,
                scene_brief=scene_brief,
                cooldown_hint=cooldown_hint,
                active_foreshadowings="（active_foreshadowings 在简化调用里省略）",
            )
            surprise_text = await self._run_crew_agent(
                self.crew.surprise(), prompt
            ) or ""
            trace["surprise"] = bool(surprise_text)

        # 0b. ForeshadowingAgent
        foreshadow_text = ""
        if run_full and self.crew is not None:
            active_foreshadowings = [
                f"- [{f.foreshadow_id}] {f.description} "
                f"(状态: {f.status.value}, 已{f.scenes_since_last_mention}场景未提及)"
                for f in project.foreshadowings
                if f.status.value in ("planted", "reinforced")
            ]
            prompt = self.crew.task_prompt(
                "foreshadowing_ops",
                project_title=project.title,
                memory_block=memory_block,
                scene_brief=scene_brief,
                present_characters=", ".join(present_chars),
                foreshadow_table="\n".join(active_foreshadowings) or "（无活跃伏笔）",
                urgent_alerts="（无紧急提醒）",
                surprise_proposal=surprise_text or "（无）",
            )
            foreshadow_text = await self._run_crew_agent(
                self.crew.foreshadowing(), prompt
            ) or ""
            trace["foreshadow"] = bool(foreshadow_text)

        # 1. DirectorAgent（回合意图包）
        director_intent = ""
        if run_full and self.crew is not None:
            prompt = self.crew.task_prompt(
                "director_plan",
                project_title=project.title,
                memory_block=memory_block,
                scene_brief=scene_brief,
                surprise_proposal=surprise_text or "（无）",
                foreshadowing_ops=foreshadow_text or "（无）",
            )
            director_intent = await self._run_crew_agent(
                self.crew.director(), prompt
            ) or ""
            trace["director"] = bool(director_intent)

        # 2. ProseAgent（文学化润色，每回合必跑）
        prose_text = ""
        if self.crew is not None:
            # 从 GM 裁决结果构建行动日志
            actor_log = "\n".join(
                f"[{r.outcome}] {r.narrative}" for r in results
            )
            director_constraints_parts = []
            if surprise_text:
                director_constraints_parts.append(f"意外事件: {surprise_text[:200]}")
            if foreshadow_text:
                director_constraints_parts.append(f"伏笔操作: {foreshadow_text[:200]}")
            if director_intent:
                director_constraints_parts.append(f"导演意图: {director_intent[:200]}")
            director_constraints = (
                "\n".join(director_constraints_parts) or "（无）"
            )
            prompt = self.crew.task_prompt(
                "prose_polish",
                style=project.style,
                director_constraints=director_constraints,
                actor_log=actor_log,
            )
            if mode == "game":
                prompt += """

===== 游戏回合输出契约 =====
只输出一个 JSON 对象，不要 Markdown 代码围栏或额外说明：
{
  "prose": "正式小说正文，不要把行动建议写进正文",
  "choices": [
    {"text": "玩家下一步可尝试的完整自然语言行动", "hint": "一句可选的代价或风险提示"}
  ],
  "stage": [{"kind": "bgm", "params": {"name": "紧张"}}]
}
choices 必须包含 3-4 项，并遵守：
1. 紧扣正文结束时的具体处境，各项应有实质差异；除了常规应对，也可建议冒险、试探或非常规做法。
2. text 是可以直接作为玩家自由输入的自然语言，不使用 move/talk 等枚举，不替玩家决定已经采取该行动。
3. 这些只是推荐，不是行动范围或成功承诺；玩家仍可输入任何其他行动。
4. hint 只作可能性提示，不虚构精确数值或保证结果，实际后果由世界裁决。
stage 只填写确实需要的表现层指令，可为空。
"""
            prose_text = await self._run_crew_agent(
                self.crew.prose(project.style), prompt
            ) or ""

        narrative = parse_agent_packet(prose_text) if prose_text else AgentPacket()
        trace["prose"] = bool(narrative.prose)
        trace["choices"] = len(narrative.choices)
        return narrative, trace

    async def _render_scene(
        self,
        state_before: WorldState,
        state_after: WorldState,
        adjudication: AdjudicationResult,
        actor: str,
        memory_context: str,
        crew_narrative: AgentPacket,
        mode: Literal["game", "director"],
    ) -> StageScene:
        """ProseAgent 已给出正文/选项/舞台段；全部缺失时走 prose_fn 兜底。"""
        packet = crew_narrative
        if not packet.prose and not packet.choices and self.prose_fn is not None:
            prompt = self._prose_prompt(
                adjudication, state_after, memory_context
            )
            try:
                prose = await asyncio.to_thread(
                    self.prose_fn, prompt, state_after
                )
            except Exception:
                prose = ""
            if str(prose).strip():
                packet = packet.model_copy(
                    update={"prose": str(prose).strip()}
                )
        return compose_scene(
            state_before, state_after, adjudication, actor, packet=packet
        )

    def _prose_prompt(
        self,
        adjudication: AdjudicationResult,
        state: WorldState,
        context: str = "",
    ) -> str:
        lines = [
            "请把下面的世界事件改写成第二人称、克制而有画面感的中文叙事，"
            "不要新增未经裁决的事实，不要复述系统提示。",
            "世界先于主角：NPC 有各自的目标与处境，不会因为玩家期待而改变；"
            "不要替玩家做决定，不要自动让玩家成功。",
            f"文风：{self.project.style}",
            f"作品设定：{self.project.description}",
        ]
        if context:
            lines.extend(["", "## 你已知的剧情与设定（仅作上下文，不必逐字引用）", context])
        lines.extend(
            [
                "",
                f"时间：{state.format_time()}",
                f"地点：{self._actor_location(state)}",
                f"裁决：{adjudication.outcome}",
                f"事实：{adjudication.narrative}",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _actor_location(state: WorldState) -> str:
        player = state.characters.get("玩家")
        if player:
            return player.location
        if state.characters:
            return next(iter(state.characters.values())).location
        return ""


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


__all__ = [
    "AgentPacket",
    "TurnBoot",
    "TurnLoop",
    "TurnResult",
    "merge_deltas",
    "parse_narrative_output",
]
