"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

双模式 TurnLoop：游戏 / 扮演与导演模式共用同一套世界状态与 SceneCrew 多 Agent 链。

    boot → perceive → classify_input → interpret_*
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
import json
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from storyloom.crews.scene_crew.crew import SceneCrew
from storyloom.extensions.host import ExtensionHost, ExtensionRegistry
from storyloom.memory.core import LayeredMemory
from storyloom.memory.legacy import SimpleRAGMemory
from storyloom.models import NovelProject
from storyloom.narrative.arc import ArcDirector, DirectorFrame
from storyloom.runtime.directive import StageScene
from storyloom.runtime.intent import (
    InterpretedIntent,
    IntentRouter,
    PlayerIntent,
)
from storyloom.runtime.renderer import SceneRenderer
from storyloom.memory.checkpoint import SaveService
from storyloom.world.autonomous_agent import autonomous_tick
from storyloom.world.authority import (
    AuthorityController,
    DirectorAuthority,
    FactOverride,
    GameAuthority,
)
from storyloom.crews.scene_crew.deterministic.gm import (
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


class SuggestedAction(BaseModel):
    """叙事 Agent 给出的自然语言行动建议，不是可执行动作白名单。"""

    text: str
    hint: str = ""


class NarrativeOutput(BaseModel):
    """ProseAgent 的游戏回合结构化输出。"""

    prose: str = ""
    suggested_actions: List[SuggestedAction] = Field(default_factory=list)


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


def parse_narrative_output(raw: str) -> NarrativeOutput:
    """解析游戏叙事 JSON；旧版纯文本输出仍可直接作为正文使用。"""
    text = raw.strip()
    if not text:
        return NarrativeOutput()

    try:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("输出中未找到 JSON 对象")
        data = json.loads(text[start:end + 1])
        if not isinstance(data, dict):
            raise ValueError("叙事输出必须是 JSON 对象")
        prose = str(data.get("prose") or "").strip()
        if not prose:
            raise ValueError("叙事输出缺少 prose")
    except (ValueError, TypeError, json.JSONDecodeError):
        return NarrativeOutput(prose=text)

    actions: List[SuggestedAction] = []
    seen = set()
    raw_actions = data.get("suggested_actions") or []
    if not isinstance(raw_actions, list):
        raw_actions = []
    for item in raw_actions:
        if isinstance(item, str):
            action_text = item.strip()
            hint = ""
        elif isinstance(item, dict):
            action_text = str(
                item.get("text") or item.get("label") or ""
            ).strip()
            hint = str(item.get("hint") or "").strip()
        else:
            continue
        if not action_text or action_text in seen:
            continue
        seen.add(action_text)
        actions.append(SuggestedAction(text=action_text, hint=hint))
        if len(actions) == 4:
            break
    return NarrativeOutput(prose=prose, suggested_actions=actions)


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

    crew / rag 都为 None 时退回原简化路径，保证旧测试通过。
    传入后游戏模式与导演模式共用同一套 SceneCrew 的叙事能力。
    """

    def __init__(
        self,
        project: NovelProject,
        instance_id: str = "default",
        memory: Optional[LayeredMemory] = None,
        extensions: Optional[ExtensionRegistry] = None,
        save_service: Optional[SaveService] = None,
        renderer: Optional[SceneRenderer] = None,
        gap_policy: str = "reject",
        crew: Optional[SceneCrew] = None,
        rag: Optional[SimpleRAGMemory] = None,
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
        self.crew = crew
        self.rag = rag
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
        action_text = (
            str(boot.intent.payload.get("text", "")).strip()
            if isinstance(boot.intent.payload, dict)
            else ""
        )
        if self.memory is not None:
            self.memory.configure_working(
                location=location,
                present_characters=present,
                scene_brief=action_text,
                # 意图应展示玩家实际输入，而不是 "text" / "choice" 这类总线类型
                intent=action_text or boot.intent.kind,
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
                        kind="checkpoint",
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
            # SceneCrew LLM 级一致性检测（有 crew 时叠加）
            if self.crew is not None:
                crew_issues = await self._crew_consistency_check(
                    working_state, before, results, actor,
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
        crew_narrative = NarrativeOutput()
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
        # crew 叙事文本作为可选的 prose 输入，优先于 renderer.prose_fn
        scene = await self._render_with_crew_prose(
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

    async def _crew_consistency_check(
        self,
        after: WorldState,
        before: WorldState,
        results: List[AdjudicationResult],
        actor: str,
        director_mode: bool = False,
    ) -> List[str]:
        """SceneCrew ConsistencyAgent 做 LLM 级人设/时间线/设定一致性检测

        与硬编码 _consistency_check 叠加；LLM 失败时返回空列表放行，
        避免阻塞回合。
        """
        issues: List[str] = []
        if self.crew is None:
            return issues

        present = after.characters_at(
            (after.characters.get(actor).location
             if after.characters.get(actor) else "")
        )
        char_summaries = []
        for name in present:
            cs = after.characters.get(name)
            if cs is None:
                continue
            profile = self.project.get_character(name)
            persona = profile.persona if profile else ""
            motivation = profile.motivation if profile else ""
            char_summaries.append(
                f"- {name}: {persona}；动机: {motivation}；"
                f"状态: {cs.status}；情绪: {cs.emotion}"
            )
        foreshadow_context = "\n".join(
            f"- [{f.foreshadow_id}] {f.description} (状态: {f.status.value})"
            for f in self.project.foreshadowings
            if f.status.value not in ("resolved", "subverted", "abandoned")
        ) or "（无活跃伏笔）"

        director_constraints = ""
        if director_mode:
            director_constraints = "导演模式：本回合内容为作者指令的直接产出，请重点检查人设与设定一致性。"

        prompt = self.crew.task_prompt(
            "consistency_check",
            actor_log="\n".join(r.narrative for r in results),
            character_data="\n".join(char_summaries) or "- （在场无角色）",
            foreshadow_data=foreshadow_context,
            director_constraints=director_constraints or "（无）",
        )
        raw = await self._run_crew_agent(self.crew.consistency(), prompt)
        if raw is None:
            return issues

        try:
            # 尝试解析 JSON（ConsistencyAgent 的结构化输出）
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                if not data.get("passed", True):
                    issues.extend(data.get("conflicts", []))
            else:
                # 纯文本格式：每行一个冲突
                for line in raw.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- ") or stripped.startswith("* "):
                        issues.append(stripped[2:])
        except (ValueError, TypeError):
            pass
        return issues

    async def _crew_narrative_round(
        self,
        mode: Literal["game", "director"],
        working_state: WorldState,
        before: WorldState,
        results: List[AdjudicationResult],
        actor: str,
        frame: DirectorFrame,
        action_text: str,
    ) -> Tuple[NarrativeOutput, Dict[str, Any]]:
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

        # RAG 上下文
        rag_context = ""
        if self.rag is not None:
            try:
                docs = self.rag.query(action_text or scene_brief, n_results=3)
                rag_context = "\n".join(docs) if docs else ""
            except Exception:
                rag_context = ""

        # 记忆上下文（用 LayeredMemory 的 prompt_block）
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
  "suggested_actions": [
    {"text": "玩家下一步可尝试的完整自然语言行动", "hint": "一句可选的代价或风险提示"}
  ]
}
suggested_actions 必须包含 3-4 项，并遵守：
1. 紧扣正文结束时的具体处境，各项应有实质差异；除了常规应对，也可建议冒险、试探或非常规做法。
2. text 是可以直接作为玩家自由输入的自然语言，不使用 move/talk 等枚举，不替玩家决定已经采取该行动。
3. 这些只是推荐，不是行动范围或成功承诺；玩家仍可输入任何其他行动。
4. hint 只作可能性提示，不虚构精确数值或保证结果，实际后果由世界裁决。
"""
            prose_text = await self._run_crew_agent(
                self.crew.prose(project.style), prompt
            ) or ""

        narrative = (
            parse_narrative_output(prose_text)
            if mode == "game" and prose_text
            else NarrativeOutput(prose=prose_text)
        )
        trace["prose"] = bool(narrative.prose)
        trace["suggested_actions"] = len(narrative.suggested_actions)
        return narrative, trace

    async def _render_with_crew_prose(
        self,
        state_before: WorldState,
        state_after: WorldState,
        adjudication: AdjudicationResult,
        actor: str,
        memory_context: str,
        crew_narrative: NarrativeOutput,
        mode: Literal["game", "director"],
    ) -> StageScene:
        """优先使用 SceneCrew 结构化叙事；无产出时走 renderer.arender。"""
        if crew_narrative.prose:
            return self.renderer._build(
                state_before,
                state_after,
                adjudication,
                actor,
                crew_narrative.prose,
                suggested_actions=[
                    action.model_dump()
                    for action in crew_narrative.suggested_actions
                ],
            )
        # 退回原有路径
        return await self.renderer.arender(
            state_before,
            state_after,
            adjudication,
            actor,
            context=memory_context,
            style=self.project.style,
            description=self.project.description,
            world_book=self._world_context(state_after, actor),
        )


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


__all__ = [
    "NarrativeOutput",
    "SuggestedAction",
    "TurnBoot",
    "TurnLoop",
    "TurnResult",
    "merge_deltas",
    "parse_narrative_output",
]
