"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

双模式统一叙事引擎：
  - 公开入口 1: generate_scene() — 导演模式（原 SceneGenerationFlow）
  - 公开入口 2: play_turn()      — 游戏模式（原 TurnLoop）
  - 内部共享:   _narrate() + _advance_world() + _gm_adjudicate()

Agent 数量减少：
  旧: SurpriseAgent + ForeshadowingAgent + DirectorAgent
      + 动态 Crew + ConsistencyAgent + ProseAgent = 6 次独立 LLM kickoff
  新: DirectorAgent（三合一，1 次 kickoff → JSON 4 部分）
      + 动态 Crew（option）+ ProseAgent = 2~3 次 LLM kickoff
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

from crewai import Agent, Crew, Process, Task
from pydantic import BaseModel, Field

from storyloom.crews.scene_crew.outline import DirectorFrame, OutlinePlanner
from storyloom.crews.scene_crew.crew import SceneCrew
from storyloom.crews.scene_crew.packet import (
    AgentPacket,
    PACKET_CONTRACT,
    compose_scene,
    packet_to_result,
    parse_agent_packet,
)
from storyloom.memory.base import (
    MEMORY_ITEM_MAX_CHARS,
    PUBLIC_VIEWERS,
)
from storyloom.crews.scene_crew.context import PromptContextAssembler
from storyloom.crews.scene_crew.offscreen import (
    drop_pending_side_stage,
    parse_pending_request,
    pending_side_stage,
)
from storyloom.crews.scene_crew.tools import CharacterWakeRegistry
from storyloom.memory import LayeredMemory
from storyloom.memory.models import (
    Foreshadowing,
    ForeshadowStatus,
    NovelProject,
)
from storyloom.memory.state import (
    ActionProposal,
    AdjudicationResult,
    FactOverride,
    StageScene,
    StateDelta,
    WorldEvent,
    WorldState,
)


# ============================================================================
# 回合预算：内层各阶段共享外层总预算，避免外层先超时
# ============================================================================

_TURN_BUDGET_RESERVE_S = 2.0
_STAGE_SIDE_STAGE_S = 2.0
_STAGE_GM_S = 8.0
_STAGE_DIRECTOR_S = 9.0
_STAGE_CREW_S = 10.0
_STAGE_PROSE_S = 8.0


class _StageBudget:
    """单回合预算：每个阶段只拿剩余时间，保证整回合在规定预算内收口。"""

    def __init__(
        self,
        total_s: float,
        reserve_s: float = _TURN_BUDGET_RESERVE_S,
    ) -> None:
        self._deadline = time.monotonic() + max(0.2, total_s - reserve_s)

    def take(self, cap_s: float) -> float:
        """返回该阶段可用秒数；预算耗尽时返回 0，由调用方走降级。"""
        remaining = self._deadline - time.monotonic()
        if remaining <= 0.05:
            return 0.0
        return min(cap_s, remaining)

    def exhausted(self) -> bool:
        return self._deadline - time.monotonic() <= 0.05


# ============================================================================
# 数据类（从 turn_flow.py 搬 + 新增）
# ============================================================================

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


class NarrateResult(BaseModel):
    """_narrate() 的结构化产出"""

    director_json: Dict[str, Any] = Field(default_factory=dict)
    actor_log: str = ""
    prose: str = ""
    choices: List[Dict[str, Any]] = Field(default_factory=list)
    consistency_issues: List[Dict[str, Any]] = Field(default_factory=list)
    quality_flags: List[str] = Field(default_factory=list)


class AdvanceResult(BaseModel):
    """_advance_world() 的结构化产出"""

    project: NovelProject
    world_state: Optional[WorldState] = None


class SceneResult(BaseModel):
    """generate_scene() 的返回"""

    prose: str
    director_json: Dict[str, Any] = Field(default_factory=dict)
    project: NovelProject
    world_state: Optional[WorldState] = None
    scene_count: int = 0


# ============================================================================
# 硬编码辅助函数（从 scene_flow.py 搬）
# ============================================================================

def parse_json_block(raw: str) -> dict:
    """从模型输出中截取并解析 JSON（推理模型常夹带说明文字）"""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(raw[start : end + 1])


def apply_foreshadow_ops(project: NovelProject, ops: List[dict]) -> None:
    """
    把导演采纳的伏笔操作应用到项目状态。

    这是防止"注意力稀释导致伏笔遗忘"的关键机制：
    每次操作都会刷新 scenes_since_last_mention，
    让状态机始终知道每条伏笔的沉睡时长。
    """
    for op in ops:
        action = op.get("action", "")
        fid = op.get("foreshadow_id")

        if action == "plant" and op.get("new_foreshadow"):
            new_data = op["new_foreshadow"]
            new_f = Foreshadowing(
                description=new_data.get("description", ""),
                planted_in_scene=f"scene_{project.scene_count}",
                target_revelation=new_data.get("target_revelation", ""),
                linked_characters=new_data.get("linked_characters", []),
                max_dormant_scenes=new_data.get("max_dormant_scenes", 5),
                visible_to=new_data.get("visible_to") or [],
            )
            project.foreshadowings.append(new_f)
            print(f"  🌱 新伏笔已种下: {new_f.description}")

        elif action == "reinforce" and fid:
            for f in project.foreshadowings:
                if f.foreshadow_id == fid:
                    f.reinforcement_count += 1
                    f.scenes_since_last_mention = 0
                    if f.status == ForeshadowStatus.PLANTED:
                        f.status = ForeshadowStatus.REINFORCED
                    print(
                        f"  💪 伏笔已强化: {f.description} "
                        f"(第{f.reinforcement_count}次)"
                    )

        elif action in ("activate", "resolve") and fid:
            for f in project.foreshadowings:
                if f.foreshadow_id == fid:
                    f.status = ForeshadowStatus(action + "d")
                    f.scenes_since_last_mention = 0
                    print(f"  🎯 伏笔已{action}: {f.description}")

        elif action == "subvert" and fid:
            for f in project.foreshadowings:
                if f.foreshadow_id == fid:
                    f.status = ForeshadowStatus.SUBVERTED
                    f.scenes_since_last_mention = 0
                    print(f"  🔄 伏笔已颠覆: {f.description}")


def advance_scene_counters(project: NovelProject) -> None:
    """场景结束后推进计数，并对超时伏笔发出警告"""
    for f in project.foreshadowings:
        if f.status in (
            ForeshadowStatus.PLANTED,
            ForeshadowStatus.REINFORCED,
        ):
            f.scenes_since_last_mention += 1

    project.scene_count += 1

    for f in project.foreshadowings:
        if (
            f.status
            in (ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED)
            and f.scenes_since_last_mention >= f.max_dormant_scenes
        ):
            print(
                f"  🚨 伏笔超时警告: [{f.foreshadow_id}] "
                f"{f.description} 已"
                f"{f.scenes_since_last_mention}场景未提及！"
            )


# ============================================================================
# NarrativeEngine 主类
# ============================================================================

class NarrativeEngine:
    """
    统一叙事引擎 + 统一世界推进 + 双模式入口。

    原来的 SceneGenerationFlow（scene_flow.py）和 TurnLoop（turn_flow.py）
    全部合并到这里。一个类，两种模式通过公开入口控制差异。

    向后兼容：__init__ 同时支持旧签名和新签名。
      旧: TurnLoop(project, crew=None, memory=None)
      新: NarrativeEngine(crew, memory)
      也可以: NarrativeEngine(project=project, crew=crew, memory=memory)
    """

    def __init__(
        self,
        crew: Optional[Any] = None,
        memory: Optional[Any] = None,
        *,
        project: Optional[NovelProject] = None,
        instance_id: str = "default",
        extensions: Optional[Any] = None,
    ) -> None:
        # ── 兼容旧 TurnLoop.__init__ 签名 ──
        # 旧签名: TurnLoop(project, instance_id, memory, extensions, save_service, prose_fn, crew)
        # 常见调用: TurnLoop(project) 或 TurnLoop(project, crew=None, memory=None)
        from storyloom.memory.models import NovelProject as _NP

        if isinstance(crew, _NP):
            # 第一个位置参数传了 NovelProject → 旧签名 TurnLoop(project)
            project = crew
            crew = None
        elif isinstance(memory, _NP):
            # 第二个位置参数传了 NovelProject → crew 参数位传了 NovelProject
            project = memory
            memory = None

        # 现在 crew 应该是 SceneCrew | None，memory 应该是 LayeredMemory | None
        self.crew: Optional[SceneCrew] = crew if not isinstance(crew, _NP) else None
        self.memory: Optional[LayeredMemory] = memory if not isinstance(memory, _NP) else None
        self.project = project  # 向后兼容旧 TurnLoop: self.project
        self.instance_id = instance_id
        self.extensions = extensions

    # ------------------------------------------------------------------
    # 公开入口 1: 导演模式（原 SceneGenerationFlow）
    # ------------------------------------------------------------------

    async def generate_scene(
        self,
        *,
        project: NovelProject,
        scene_brief: str,
        present_chars: List[str],
        world_state: Optional[WorldState] = None,
        is_regenerate: bool = False,
        max_retries: int = 1,
        max_duration_s: Optional[float] = None,
    ) -> SceneResult:
        """
        导演模式入口：生成一个完整场景。

        流程：
          _narrate(mode="director", enable_crew=True)
          → _advance_world(mode="director")
          → 返回 SceneResult(prose, director_json, project, world_state)
        """
        # 回合间推进：先落地上一轮登记的异步侧台请求
        budget = _StageBudget(max_duration_s) if max_duration_s else None
        side_stage_echo = await self.drain_side_stage(
            project=project,
            present_chars=present_chars,
            scene_brief=scene_brief,
            budget=budget,
        )
        pre_context = (
            {"side_stage_echo": side_stage_echo} if side_stage_echo else None
        )

        narrate_result = await self._narrate(
            project=project,
            scene_brief=scene_brief,
            present_chars=present_chars,
            mode="director",
            pre_context=pre_context,
            enable_crew=True,
            enable_consistency=True,
            max_retries=max_retries,
            budget=budget,
        )

        # 一致性 major 冲突时已在 _narrate 内 retry，这里不再阻塞

        advance_result = await self._advance_world(
            project=project,
            prose=narrate_result.prose,
            scene_brief=scene_brief,
            present_chars=present_chars,
            director_json=narrate_result.director_json,
            world_state=world_state,
            state_delta=None,
            mode="director",
            is_regenerate=is_regenerate,
        )

        return SceneResult(
            prose=narrate_result.prose,
            director_json=narrate_result.director_json,
            project=advance_result.project,
            world_state=advance_result.world_state,
            scene_count=advance_result.project.scene_count,
        )

    # ------------------------------------------------------------------
    # 公开入口 2: 游戏模式（原 TurnLoop 核心叙事链）
    # ------------------------------------------------------------------

    async def play_turn(
        self,
        *,
        project: NovelProject,
        world_state: WorldState,
        actor: str = "玩家",
        action_text: str = "",
        wait: bool = False,
        max_retries: int = 1,
        frame: Optional[DirectorFrame] = None,
        idle_turns: int = 0,
        mode: Literal["game", "director"] = "game",
        goal: str = "",
        instance_id: str = "default",
        max_duration_s: float = 30.0,
    ) -> TurnResult:
        """
        游戏模式入口：跑一个玩家回合。

        流程：
          ① perceive（从 WorldState 取 location + present）
          ② GM adjudicate（导演 Agent 裁决 → StateDelta + narrative）
          ③ _narrate(mode="game", enable_crew=False, pre_context=GM 结果)
          ④ _advance_world(mode="game", state_delta=GM 产出)
          ⑤ arc 推进（OutlinePlanner）
          ⑥ render（compose_scene）
          → 返回 TurnResult

        idle_turns >= 3 时触发 NPC 事件轮（_npc_round_fallback）。
        """
        start = time.time()
        turn_id = uuid.uuid4().hex[:12]
        trace_id = uuid.uuid4().hex
        budget = _StageBudget(max_duration_s)
        degraded_flags: List[str] = []

        # ① perceive（先合入扩展地图 / 旅行耗时，只增不删）
        if world_state is None:
            world_state = WorldState.from_project(project, mode=mode)
        # 同步 mode 到 world_state（旧 TurnLoop._prepare_state 的职责）
        if mode != world_state.mode:
            world_state = world_state.model_copy(update={"mode": mode})
        if self.extensions is not None:
            world_state = self.extensions.apply_map(world_state)
            travel = self.extensions.travel_overrides()
            if travel:
                world_state = world_state.model_copy(deep=True)
                for key, minutes in travel.items():
                    origin, _, dest = key.partition("->")
                    if origin in world_state.locations and dest:
                        world_state.locations[origin].exits[dest] = minutes
        location = world_state.location_of(actor) or ""
        present = world_state.characters_at(location)
        present = present or [actor]

        # memory 工作区：同步 location / present / intent / time
        if self.memory is not None:
            try:
                self.memory.configure_working(
                    location=location,
                    present_characters=present,
                    scene_brief=action_text.strip() or "(等待)",
                    intent=action_text.strip() or ("等待" if wait else ""),
                    time=world_state.format_time(),
                )
            except Exception:
                pass

        # 回合间推进：把上一回合登记的异步侧台请求落地为记忆与世界书
        side_stage_echo = await self.drain_side_stage(
            project=project,
            present_chars=present,
            scene_brief=action_text.strip() or "(等待)",
            budget=budget,
        )

        # ② 导演帧（先定节拍，再裁决） + GM adjudicate + idle_turns NPC round
        arc_planner = OutlinePlanner()
        arc_frame = frame or arc_planner.frame(world_state, goal=goal)

        adjudication = None
        state_delta = StateDelta()
        pre_context_gm = None

        # 玩家有行动文本才跑玩家 GM 裁决；wait=True 且无文本时跳过
        if action_text or not wait:
            proposal = ActionProposal(
                actor=actor,
                kind="wait" if wait else "other",
                detail=action_text,
                source="player",
            )
            adjudication, state_delta = await self._gm_adjudicate(
                proposal=proposal,
                state=world_state,
                mode=mode,
                frame=arc_frame,
                budget=budget,
                degraded_flags=degraded_flags,
            )
            pre_context_gm = {
                "gm_verdict": adjudication.narrative,
                "player_success": adjudication.success,
                "outcome": adjudication.outcome,
            }

        if side_stage_echo:
            pre_context_gm = dict(pre_context_gm or {})
            pre_context_gm["side_stage_echo"] = side_stage_echo

        # idle_turns >= 3 时触发 NPC 事件轮（硬编码降级），事件并入本回合 delta
        if idle_turns >= 3:
            npc_delta = self._npc_round_fallback(world_state, actor)
            state_delta.events.extend(npc_delta.events)

        # ③ 统一叙事生成（pre_context 传 GM 结果）
        narrate_result = await self._narrate(
            project=project,
            scene_brief=action_text or "(等待)",
            present_chars=present,
            mode=mode,
            pre_context=pre_context_gm,
            enable_crew=False,  # 游戏模式跳过动态 Crew
            enable_consistency=True,
            max_retries=max_retries,
            budget=budget,
        )

        # ④ 统一世界推进（只 apply 一次 delta，使用返回的对齐后状态）
        advance_result = await self._advance_world(
            project=project,
            prose=narrate_result.prose,
            scene_brief=action_text or "(等待)",
            present_chars=present,
            director_json=narrate_result.director_json,
            world_state=world_state,
            state_delta=state_delta,
            mode=mode,
            is_regenerate=False,
        )
        working_state = advance_result.world_state or world_state

        # ⑤ arc 推进（确定性节拍：成功微调张力，戏剧性结果放大张力）
        arc = arc_planner.advance(
            working_state,
            success=(adjudication is None or adjudication.success),
            dramatic=bool(
                adjudication
                and adjudication.outcome in ("hit", "intercepted")
            ),
        )
        working_state = working_state.model_copy(update={"arc": arc})
        arc_result: Optional[DirectorFrame] = arc_planner.frame(
            working_state, goal=goal
        )

        # ⑥ render（compose_scene）
        packet = AgentPacket(
            prose=narrate_result.prose,
            choices=[],
            issues=[
                str(c.get("conflict"))
                for c in narrate_result.consistency_issues
                if c.get("severity") == "major"
            ],
        )
        from storyloom.crews.scene_crew.packet import AgentChoice

        packet.choices = [
            AgentChoice(text=c.get("text", ""), hint=c.get("hint", ""))
            for c in narrate_result.choices[:4]
        ]

        adjudication_for_render = adjudication or AdjudicationResult(
            success=True, outcome="narrated", narrative="",
            rule="idle_narrative",
        )
        scene = compose_scene(
            state_before=world_state,
            state_after=working_state,
            adjudication=adjudication_for_render,
            actor=actor,
            packet=packet,
        )

        status: Literal["ok", "rejected"] = (
            "ok" if (adjudication is None or adjudication.success) else "rejected"
        )
        end_arc = (
            working_state.arc.phase == "resolution"
            and working_state.arc.beats_remaining <= 1
        )
        exit_flag: Literal["next_turn", "end_arc"] = (
            "end_arc" if end_arc else "next_turn"
        )

        elapsed_ms = int((time.time() - start) * 1000)
        degrade_flags = [*degraded_flags, *narrate_result.quality_flags]
        quality_flags = list(degrade_flags)
        if adjudication is not None and not adjudication.success:
            quality_flags.append("rejected")
        return TurnResult(
            turn_id=turn_id,
            trace_id=trace_id,
            project_id=getattr(project, "project_id", "") or "",
            instance_id=instance_id,
            status=status,
            exit=exit_flag,
            state=working_state,
            state_delta=state_delta,
            scene=scene,
            text=narrate_result.prose,
            choices=narrate_result.choices,
            quality=max(0.3, 1.0 - 0.2 * len(degrade_flags)),
            quality_flags=quality_flags,
            frame=arc_result,
            log={
                "elapsed_ms": elapsed_ms,
                "scene_count": project.scene_count,
                "degraded": degrade_flags,
            },
        )

    # ------------------------------------------------------------------
    # 回合间推进：异步侧台
    # ------------------------------------------------------------------

    async def drain_side_stage(
        self,
        *,
        project: NovelProject,
        present_chars: List[str],
        scene_brief: str,
        max_events: int = 2,
        budget: Optional[_StageBudget] = None,
    ) -> str:
        """把上一回合登记的异步侧台请求落地。

        游戏模式下 ``wake_character`` 只写入一条 pending 记忆条目；
        下一次进入叙事（游戏回合或导演场景）时在这里统一推进：
        裁决沉睡角色之间的互动、唤醒目标角色、把事实/视角/消息
        写入短期记忆与世界书，并返回可注入叙事的「侧台回响」。
        """
        if self.crew is None or self.memory is None:
            return ""
        pending = pending_side_stage(self.memory)
        if not pending:
            return ""

        registry = CharacterWakeRegistry(
            crew=self.crew,
            project=project,
            present_chars=list(present_chars),
            memory=self.memory,
            scene_brief=scene_brief,
            scene_index=project.scene_count,
            max_wakes=max_events,
            defer_side_stage=False,
            assembler=PromptContextAssembler(
                memory=self.memory,
                project=project,
                scene_brief=scene_brief,
                present_chars=list(present_chars),
                foreshadow_table=self._foreshadow_summary(project),
                extensions=self.extensions,
            ),
        )
        present = set(present_chars)
        seen_focus: set = set()
        processed = 0

        for item in pending:
            if processed >= max_events:
                break
            item_id = getattr(item, "id", "")
            payload = parse_pending_request(getattr(item, "text", "") or "")
            if not payload:
                drop_pending_side_stage(self.memory, item_id)
                continue

            focus = str(payload.get("focus") or "").strip()
            char = project.get_character(focus)
            if (
                char is None
                or char.importance_tier == "background"
                or focus in present
                or focus in seen_focus
            ):
                # 角色已删除 / 已到场 / 重复登记：无需远程回复
                drop_pending_side_stage(self.memory, item_id)
                continue
            seen_focus.add(focus)

            others = [
                str(name)
                for name in (payload.get("participants") or [])
                if name and str(name) != focus
            ]
            before = len(registry.records)
            wake_timeout = (
                budget.take(_STAGE_SIDE_STAGE_S) if budget is not None else 30.0
            )
            if budget is not None and wake_timeout <= 0:
                # 预算耗尽：保留 pending，留到下个回合处理
                break
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        registry.wake,
                        focus,
                        str(payload.get("reason") or ""),
                        ", ".join(others),
                        f"async:{payload.get('source') or 'director'}",
                    ),
                    timeout=wake_timeout,
                )
            except Exception:  # noqa: BLE001 - 单个请求失败/超时不影响其他
                pass
            # 无论成功与否都清理请求，避免每回合反复重试
            drop_pending_side_stage(self.memory, item_id)
            if len(registry.records) > before:
                processed += 1

        block = registry.transcript_block()
        if not block:
            return ""
        return (
            "【侧台回响】以下远程互动在回合之间已经发生，"
            "请在本回合自然带入：\n"
            f"{block}"
        )

    # ------------------------------------------------------------------
    # 内部统一方法 1: 叙事生成（Director → 可选 Crew → Prose）
    # ------------------------------------------------------------------

    async def _narrate(
        self,
        *,
        project: NovelProject,
        scene_brief: str,
        present_chars: List[str],
        mode: Literal["director", "game"],
        pre_context: Optional[Dict[str, Any]] = None,
        enable_crew: bool = True,
        enable_consistency: bool = True,
        max_retries: int = 1,
        budget: Optional[_StageBudget] = None,
    ) -> NarrateResult:
        """
        2~3 次 LLM kickoff 的统一叙事链：

        Step 1: DirectorAgent（合成 surprise + intent + foreshadow + consistency）
                1 次 kickoff → JSON 4 部分
                Tools: query_active_foreshadows（按需 function call）

        Step 2: 动态 Crew（option，enable_crew=False 就跳过）

        Step 3: ProseAgent

        一致性: DirectorAgent JSON 的 consistency 字段 + 硬编码规则
                严重冲突触发 retry
        """
        # ---- Step 0: 惰性角色唤醒登记表 + 统一上下文装配器 ----
        # 所有 Agent 共用同一个 assembler（同一份场景上下文 + 同一个记忆库），
        # 区别只在 viewer 与各维度开关。
        assembler = PromptContextAssembler(
            memory=self.memory,
            project=project,
            scene_brief=scene_brief,
            present_chars=list(present_chars),
            foreshadow_table=self._foreshadow_summary(project),
            extensions=self.extensions,
        )

        wake_registry: Optional[CharacterWakeRegistry] = None
        if self.crew is not None:
            wake_registry = CharacterWakeRegistry(
                crew=self.crew,
                project=project,
                present_chars=list(present_chars),
                memory=self.memory,
                scene_brief=scene_brief,
                scene_index=project.scene_count,
                max_wakes=2,
                # 游戏模式走异步侧台：只登记，回应在回合间推进后送达
                defer_side_stage=(mode == "game"),
                assembler=assembler,
            )

        # ---- Step 1: DirectorAgent kickoff ----
        director_json = {}
        quality_flags: List[str] = []
        for attempt in range(max_retries + 1):
            # crew 不可用 → 硬编码降级
            if self.crew is None:
                director_json = self._fallback_director_json(scene_brief, mode)
                break

            director_timeout = (
                budget.take(_STAGE_DIRECTOR_S) if budget is not None else 90.0
            )
            if director_timeout <= 0:
                director_json = self._fallback_director_json(scene_brief, mode)
                quality_flags.append("director_degraded")
                break

            director_prompt = self._build_director_prompt(
                assembler=assembler,
                mode=mode,
                pre_context=pre_context,
            )
            if wake_registry is not None:
                # 只有实际给导演挂了 wake_character tool 时才在 prompt 里
                # 宣传该能力，避免其他导演调用（如裁定）误用不存在的工具。
                director_prompt = (
                    f"{director_prompt}\n{wake_registry.prompt_block()}"
                )
            director_agent = self.crew.build_director(
                extra_tools=(
                    [wake_registry.make_tool(source="director")]
                    if wake_registry is not None
                    else None
                )
            )
            raw = await self._kickoff(
                agent=director_agent,
                prompt=director_prompt,
                timeout_s=director_timeout,
            )
            if raw is None:
                # LLM 不可用 / 超时 → 用降级 JSON
                director_json = self._fallback_director_json(scene_brief, mode)
                quality_flags.append("director_degraded")
                break

            try:
                director_json = parse_json_block(raw)
            except (ValueError, json.JSONDecodeError):
                # 解析失败 → 用降级
                director_json = self._fallback_director_json(scene_brief, mode)
                break

            # 一致性检查
            issues = self._hardcode_checks(director_json, project, mode)
            consistency_section = director_json.get("consistency", {})
            director_passed = consistency_section.get("passed", True)
            director_conflicts = consistency_section.get("conflicts", [])

            has_major = any(
                c.get("severity") == "major"
                for c in director_conflicts
                if isinstance(c, dict)
            ) or any(
                c.get("severity") == "major"
                for c in issues
                if isinstance(c, dict)
            )

            if not director_passed or has_major:
                if attempt < max_retries and (
                    budget is None or not budget.exhausted()
                ):
                    print(
                        f"  ⚠️ DirectorAgent 一致性 major 冲突，"
                        f"retry {attempt + 1}/{max_retries}..."
                    )
                    continue
            break

        if not director_json:
            director_json = self._fallback_director_json(scene_brief, mode)

        if wake_registry is not None:
            wake_registry.intent = json.dumps(
                director_json.get("director_intent", {}),
                ensure_ascii=False,
            )
        # 导演意图回写给 assembler，供后续角色 Agent 使用
        assembler.director_intent = wake_registry.intent if wake_registry else json.dumps(
            director_json.get("director_intent", {}), ensure_ascii=False
        )

        # ---- Step 2: 动态 Crew（option） ----
        actor_log = ""
        rag_context = assembler.rag_context("director", query=scene_brief, k=3)

        if enable_crew and mode == "director" and self.crew is not None:
            actor_log = await self._run_dynamic_crew(
                project=project,
                present_chars=present_chars,
                director_json=director_json,
                rag_context=rag_context,
                memory_query=scene_brief,
                wake_registry=wake_registry,
                assembler=assembler,
                budget=budget,
                quality_flags=quality_flags,
            )
        else:
            # 游戏模式、禁用 Crew、或 crew 不可用 → actor_log 直接从 pre_context 取
            actor_log = self._actor_log_from_pre_context(pre_context)

        # 导演或在场主角可能已唤醒不在场角色：把回应并入角色日志，
        # 让 ProseAgent 真正使用这些「远程参与」的言行。
        if wake_registry is not None:
            wake_log = wake_registry.transcript_block()
            if wake_log:
                actor_log = f"{actor_log}\n\n{wake_log}".strip()

        # 异步侧台在回合间推进的结果，本回合由叙事者自然带入
        side_stage_echo = (pre_context or {}).get("side_stage_echo") or ""
        if side_stage_echo:
            actor_log = f"{actor_log}\n\n{side_stage_echo}".strip()

        # ---- Step 3: ProseAgent kickoff ----
        prose = ""
        choices: List[Dict[str, Any]] = []

        # crew 不可用 → 直接用 scene_brief 作为 prose
        if self.crew is None:
            prose = scene_brief or (pre_context or {}).get("gm_verdict", "")
        else:
            prose_timeout = (
                budget.take(_STAGE_PROSE_S) if budget is not None else 90.0
            )
            if prose_timeout <= 0:
                quality_flags.append("prose_degraded")
            else:
                prose_prompt = self._build_prose_prompt(
                    actor_log=actor_log,
                    director_json=director_json,
                    mode=mode,
                    project=project,
                )
                raw_prose = await self._kickoff(
                    agent=self.crew.prose(),
                    prompt=prose_prompt,
                    timeout_s=prose_timeout,
                )
                if raw_prose is not None:
                    packet = parse_agent_packet(raw_prose)
                    prose = packet.prose or raw_prose.strip()
                    choices = [
                        {"text": c.text, "hint": c.hint} for c in packet.choices
                    ]
                else:
                    quality_flags.append("prose_degraded")

        # 正文阶段降级时仍返回可读文本，避免整回合只有空串
        if not prose:
            prose = (
                (pre_context or {}).get("gm_verdict", "")
                or scene_brief
            )

        return NarrateResult(
            director_json=director_json,
            actor_log=actor_log,
            prose=prose,
            choices=choices,
            consistency_issues=self._hardcode_checks(director_json, project, mode),
            quality_flags=quality_flags,
        )

    # ------------------------------------------------------------------
    # 内部统一方法 2: 世界推进（硬编码，无 LLM）
    # ------------------------------------------------------------------

    async def _advance_world(
        self,
        *,
        project: NovelProject,
        prose: str,
        scene_brief: str,
        present_chars: List[str],
        director_json: Dict[str, Any],
        world_state: Optional[WorldState] = None,
        state_delta: Optional[StateDelta] = None,
        mode: Literal["director", "game"] = "director",
        is_regenerate: bool = False,
    ) -> AdvanceResult:
        """
        统一世界推进（全部硬编码，无 LLM）。

        用 self.memory（构造时注入的）。

        advance_scene_counters → apply_foreshadow_ops → memory.add_scene
        → world_state.apply_delta（有就推进）→ 双向对齐 → 返回

        两条链路都调这一处，消除 TurnLoop 里的僵尸状态。
        """
        memory = self.memory

        # 1. advance_scene_counters（非重跑才推进）
        if not is_regenerate:
            advance_scene_counters(project)

        # 2. apply_foreshadow_ops（DirectorAgent JSON 里决定的伏笔操作）
        ops = director_json.get("foreshadow_ops", [])
        if ops and isinstance(ops, list):
            apply_foreshadow_ops(project, ops)
            if memory is not None:
                memory.sync_foreshadowings(project.foreshadowings)

        # 3. memory 写入：优先用 Agent 在 JSON 里附带的 memory_facts
        # （预压缩好的核心记忆，调用次数不增加）；缺省时回退到
        # add_scene（内部会对 prose 做 summarize，不直接存原文）。
        scene_idx = project.scene_count
        if memory is not None:
            _apply_memory_facts(
                memory=memory,
                facts=director_json.get("memory_facts"),
                scene_index=scene_idx,
                prose=prose,
                brief=scene_brief,
                present_chars=present_chars,
            )

        # 4. WorldState 推进（有就推，没有就跳过）
        if world_state is not None:
            if state_delta is None:
                state_delta = self._infer_delta(mode, scene_brief)
            world_state = world_state.apply_delta(state_delta, advance_turn=False)
            # 双向对齐（只增不减）
            world_state.turn = max(world_state.turn, project.scene_count)
            project.scene_count = max(project.scene_count, world_state.turn)
            # 5. 回忆型状态投影到 memory（权威真相仍在 world_state）
            if memory is not None:
                memory.sync_world_state(world_state, current_scene=scene_idx)

        return AdvanceResult(project=project, world_state=world_state)

    # ------------------------------------------------------------------
    # GM 裁决（原 TurnLoop 独有，现在也归 NarrativeEngine）
    # ------------------------------------------------------------------

    async def _gm_adjudicate(
        self,
        *,
        proposal: ActionProposal,
        state: WorldState,
        mode: Literal["game", "director"] = "game",
        frame: Optional[DirectorFrame] = None,
        budget: Optional[_StageBudget] = None,
        degraded_flags: Optional[List[str]] = None,
    ) -> Tuple[AdjudicationResult, StateDelta]:
        """
        GM 裁决：DirectorAgent 产出 StateDelta + narrative。

        crew=None 时走硬编码降级路径（_fallback_adjudicate），保证测试通过。
        """
        actor = state.characters.get(proposal.actor)
        if actor is None:
            return (
                AdjudicationResult(
                    success=False,
                    outcome="rejected",
                    error_code="actor_not_found",
                    narrative=f"不存在的行动者：{proposal.actor}",
                    rule="existence",
                ),
                StateDelta(),
            )
        if actor.status == "dead":
            return (
                AdjudicationResult(
                    success=False,
                    outcome="rejected",
                    error_code="actor_dead",
                    narrative="你已经无法行动。",
                    rule="existence",
                ),
                StateDelta(),
            )

        # crew 不可用 → 硬编码降级
        if self.crew is None:
            fallback = self._fallback_adjudicate(proposal, state)
            return fallback, fallback.state_delta

        gm_timeout = budget.take(_STAGE_GM_S) if budget is not None else 60.0
        if gm_timeout <= 0:
            if degraded_flags is not None:
                degraded_flags.append("gm_degraded")
            fallback = self._fallback_adjudicate(proposal, state)
            return fallback, fallback.state_delta

        prompt = self.crew._adjudication_prompt(proposal, state, mode, frame)
        raw = await self._kickoff(
            agent=self.crew.director(), prompt=prompt, timeout_s=gm_timeout
        )
        if raw is None:
            if degraded_flags is not None:
                degraded_flags.append("gm_degraded")
            fallback = self._fallback_adjudicate(proposal, state)
            return fallback, fallback.state_delta

        packet = parse_agent_packet(raw)
        result = packet_to_result(packet, default_narrative=proposal.detail)
        if result.success:
            if result.state_delta.time_delta <= 0:
                result.state_delta.time_delta = 1
            if not result.state_delta.events:
                result.state_delta.events.append(
                    state.touch(
                        "action",
                        proposal.actor,
                        proposal.detail or result.narrative,
                    )
                )
        return result, result.state_delta

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    async def _kickoff(
        self, agent: Agent, prompt: str, timeout_s: float = 60.0
    ) -> Optional[str]:
        """同步 kickoff 的异步包装；不可用或超时返回 None。"""
        if self.crew is not None and hasattr(self.crew, "run_agent"):
            return await self.crew.run_agent(agent, prompt, timeout_s)

        loop = asyncio.get_event_loop()

        def _sync_kickoff() -> Any:
            return agent.kickoff(prompt)

        try:
            output = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_kickoff), timeout=timeout_s
            )
            return str(output.raw).strip() if output else None
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    def _build_director_prompt(
        self,
        *,
        assembler: PromptContextAssembler,
        mode: Literal["director", "game"],
        pre_context: Optional[Dict[str, Any]],
    ) -> str:
        """构造 DirectorAgent 的提示词

        所有共享维度（场景/角色一览/伏笔/记忆/RAG/扩展）由 assembler 统一注入，
        这里只负责导演独有的部分：模式提示、pre_context、输出 schema。
        """
        # 模式差异
        mode_hint = (
            "导演模式：你为本【场景】做完整意图规划，"
            "scene_brief 是场景描述。"
            if mode == "director"
            else "游戏模式：玩家刚刚行动完毕，GM 已裁决（见 pre_context），"
            "你在此基础上做叙事意图规划。action_text 是玩家行动。"
        )

        pre_context_str = ""
        if pre_context:
            if mode == "game" and "gm_verdict" in pre_context:
                pre_context_str = (
                    "\n\n【GM 裁决结果】\n"
                    f"裁决叙事: {pre_context.get('gm_verdict', '')}\n"
                    f"玩家是否成功: {'是' if pre_context.get('player_success') else '否'}\n"
                    f"结局类型: {pre_context.get('outcome', '')}\n"
                )
            echo = pre_context.get("side_stage_echo")
            if echo:
                pre_context_str += (
                    "\n【侧台回响（上一回合异步落地）】\n"
                    f"{echo}\n"
                    "请在本场叙事中自然带入这些远程互动，"
                    "不要重复已发生的事实，也不要替角色补充新的秘密。\n"
                )

        # 导演用全知视角读取全部共享维度
        shared_context = assembler.build(
            "director",
            query=assembler.scene_brief,
            include_scene=True,
            include_cast=True,
            include_foreshadow=True,
            include_extension=True,
        )

        classical_memory = bool(
            self.memory is not None
            and self.memory.settings.classical_compression
        )
        memory_fact_schema = (
            '  "memory_facts": [ { "tier": "short_term", "text": "…", '
            '"display_text": "…", "visible_to": [], "tags": [] } ]\n'
        )
        memory_fact_rule = (
            "memory_facts 用 text 存文言文，display_text 存同义白话文；"
            "缺少 display_text 的记忆会被丢弃。"
            if classical_memory
            else "memory_facts 的 text 用白话文；display_text 可省略。"
        )

        return self.crew.task_prompt(
            "director_plan",
            mode_hint=mode_hint,
            shared_context=shared_context,
            pre_context=pre_context_str,
            memory_fact_schema=memory_fact_schema,
            memory_fact_rule=memory_fact_rule,
        )

    def _build_prose_prompt(
        self,
        *,
        actor_log: str,
        director_json: Dict[str, Any],
        mode: Literal["director", "game"],
        project: NovelProject,
    ) -> str:
        """构造 ProseAgent 的提示词"""
        intent = director_json.get("director_intent", {})
        intent_str = json.dumps(intent, ensure_ascii=False, indent=2)
        style = getattr(project, "style", "") or ""

        output_hint = (
            "只输出 prose 正文段（一段流畅的中文叙事）。"
            if mode == "director"
            else "输出 JSON 对象：{\"prose\":\"正文\", \"choices\":[{\"text\":\"...\",\"hint\":\"...\"},...]}。choices 给 3~4 个自然语言行动建议。"
        )

        return self.crew.task_prompt(
            "prose_polish",
            packet_contract=PACKET_CONTRACT,
            output_hint=output_hint,
            director_intent=intent_str,
            actor_log=actor_log or "（无角色互动，直接进入叙事）",
            style=style or "（默认细腻文风）",
        )

    async def _run_dynamic_crew(
        self,
        *,
        project: NovelProject,
        present_chars: List[str],
        director_json: Dict[str, Any],
        rag_context: str,
        memory_query: str = "",
        wake_registry: Optional[CharacterWakeRegistry] = None,
        assembler: Optional[PromptContextAssembler] = None,
        budget: Optional[_StageBudget] = None,
        quality_flags: Optional[List[str]] = None,
    ) -> str:
        """
        动态 Crew 组装 + kickoff。

        搬自 scene_flow.py run_actor_interaction (L374~L450)。
        primary 角色 → 每个独立一个 ProtagonistAgent
        secondary 角色 → 合并给 EnsembleAgent
        """
        primary_chars = [
            c
            for c in project.characters
            if c.name in present_chars and c.importance_tier == "primary"
        ]
        secondary_chars = [
            c
            for c in project.characters
            if c.name in present_chars and c.importance_tier != "primary"
        ]

        # 每个可并行单元 = 一组互不共享 Agent 的 Task；
        # primary 角色一人一 Agent，可彼此并行；secondary 共用 ensemble，组内串行。
        units: List[Tuple[List[Agent], List[Task]]] = []

        intent_block = (
            assembler.intent_block()
            if assembler is not None
            else f"导演意图:\n{json.dumps(director_json.get('director_intent', {}), ensure_ascii=False, indent=2)}"
        )

        wakeable_names = (
            [c.name for c in wake_registry.wakeable_characters()]
            if wake_registry is not None
            else []
        )
        wake_hint = (
            "\n若你需要联系不在场的重要角色（"
            + ", ".join(wakeable_names)
            + "），可调用 wake_character tool 唤醒他/她；"
            "若知道对方最近和其他沉睡角色有互动，传入 involves；"
            "不需要时不要调用。\n"
            if wakeable_names
            else ""
        )

        def char_memory(char) -> tuple[str, str]:
            if assembler is None:
                return "", rag_context
            return (
                assembler.memory_block(char.name),
                assembler.rag_context(char.name, memory_query, k=3),
            )

        for char in primary_chars:
            extra_tools = (
                [wake_registry.make_tool(source=f"protagonist:{char.name}")]
                if wake_registry is not None
                else None
            )
            agent = self.crew.build_protagonist(char, extra_tools=extra_tools)
            memory_block, char_rag = char_memory(char)
            task = Task(
                description=self.crew.task_prompt(
                    "actor_interaction",
                    character_name=char.name,
                    wake_hint=wake_hint,
                    intent_block=intent_block,
                    rag_context=char_rag,
                    memory_block=memory_block,
                ),
                expected_output=self.crew.task_expected_output(
                    "actor_interaction", character_name=char.name
                ),
                agent=agent,
            )
            units.append(([agent], [task]))

        if secondary_chars:
            ensemble = self.crew.ensemble(secondary_chars)
            secondary_tasks: List[Task] = []
            for char in secondary_chars:
                memory_block, char_rag = char_memory(char)
                secondary_tasks.append(
                    Task(
                        description=self.crew.task_prompt(
                            "actor_interaction_secondary",
                            character_name=char.name,
                            intent_block=intent_block,
                            rag_context=char_rag,
                            memory_block=memory_block,
                        ),
                        expected_output=self.crew.task_expected_output(
                            "actor_interaction_secondary",
                            character_name=char.name,
                        ),
                        agent=ensemble,
                    )
                )
            units.append(([ensemble], secondary_tasks))

        if not units:
            # 没有出场角色 → 跳过 Crew
            intent = director_json.get("director_intent", {})
            return f"（无角色互动）导演意图: {intent.get('goal', '')}"

        # 每个单元独立成 Crew：primary 角色之间并行，secondary 组内仍串行
        crews = [
            Crew(
                agents=unit_agents,
                tasks=unit_tasks,
                process=Process.sequential,
            )
            for unit_agents, unit_tasks in units
        ]

        crew_timeout = budget.take(_STAGE_CREW_S) if budget is not None else 120.0
        if crew_timeout <= 0:
            if quality_flags is not None:
                quality_flags.append("crew_degraded")
            return ""

        loop = asyncio.get_running_loop()

        def _sync_kickoff(target: Crew) -> Any:
            return target.kickoff()

        async def _run_unit(target: Crew) -> Any:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _sync_kickoff, target),
                timeout=crew_timeout,
            )

        results = await asyncio.gather(
            *(_run_unit(target) for target in crews), return_exceptions=True
        )
        if any(isinstance(r, asyncio.TimeoutError) for r in results):
            print("  ⏱️ 动态 Crew kickoff 超时，跳过角色互动")
            if quality_flags is not None:
                quality_flags.append("crew_degraded")
            return ""
        outputs: List[str] = []
        for result in results:
            if isinstance(result, Exception):
                print(f"  ⚠️ 动态 Crew kickoff 失败: {result}")
                continue
            text = str(result).strip() if result else ""
            if text:
                outputs.append(text)
        return "\n\n".join(outputs)

    def _hardcode_checks(
        self,
        director_json: Dict[str, Any],
        project: NovelProject,
        mode: Literal["director", "game"],
    ) -> List[Dict[str, Any]]:
        """
        硬编码一致性检查（永远跑，O(1)）。

        返回格式: [{"severity": "major|minor|none", "conflict": "..."}]
        """
        issues: List[Dict[str, Any]] = []

        # 检查 foreshadow_ops 引用的 foreshadow_id 是否存在
        ops = director_json.get("foreshadow_ops", [])
        valid_ids = {f.foreshadow_id for f in project.foreshadowings}
        for op in ops:
            fid = op.get("foreshadow_id")
            if fid and op.get("action") in ("reinforce", "resolve", "subvert"):
                if fid not in valid_ids:
                    issues.append(
                        {
                            "severity": "minor",
                            "conflict": f"引用了不存在的伏笔 {fid}",
                        }
                    )

        # 检查 intent.key_events 不能为空
        intent = director_json.get("director_intent", {})
        if not intent.get("goal"):
            issues.append(
                {
                    "severity": "minor",
                    "conflict": "director_intent.goal 为空",
                }
            )

        return issues

    # ------------------------------------------------------------------
    # 回溯伏笔冲突检查
    # ------------------------------------------------------------------

    @staticmethod
    def _scene_index_of(label: str) -> Optional[int]:
        if not label:
            return None
        token = str(label).rsplit("_", 1)[-1]
        return int(token) if token.isdigit() else None

    def _hardcode_foreshadow_checks(
        self,
        project: NovelProject,
        fs: Foreshadowing,
        scenes: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """回溯插入伏笔前的结构检查（不调用 LLM）。"""
        issues: List[Dict[str, Any]] = []
        names = {c.name for c in project.characters}
        for name in fs.visible_to:
            if name in PUBLIC_VIEWERS:
                continue
            if name not in names and name != "crowd":
                issues.append(
                    {
                        "severity": "major",
                        "conflict": f"知情角色不存在：{name}",
                    }
                )
        for name in fs.linked_characters:
            if name not in names and name != "crowd":
                issues.append(
                    {
                        "severity": "major",
                        "conflict": f"关联角色不存在：{name}",
                    }
                )

        idx = self._scene_index_of(fs.planted_in_scene)
        if idx is None:
            issues.append(
                {
                    "severity": "major",
                    "conflict": f"无法解析埋设场景：{fs.planted_in_scene}",
                }
            )
        elif idx > project.scene_count:
            issues.append(
                {
                    "severity": "major",
                    "conflict": (
                        f"埋设场景 {fs.planted_in_scene} 晚于当前进度 "
                        f"scene_{project.scene_count}"
                    ),
                }
            )

        for other in project.foreshadowings:
            if other.foreshadow_id == fs.foreshadow_id:
                continue
            same_desc = other.description.strip() == fs.description.strip()
            other_truth = other.target_revelation.strip()
            same_truth = bool(other_truth) and (
                other_truth == fs.target_revelation.strip()
            )
            if same_desc and other_truth != fs.target_revelation.strip():
                issues.append(
                    {
                        "severity": "major",
                        "conflict": (
                            f"与已有伏笔 {other.foreshadow_id} 描述相同"
                            "但真相不同"
                        ),
                    }
                )
            elif same_truth and not same_desc:
                issues.append(
                    {
                        "severity": "minor",
                        "conflict": (
                            f"与已有伏笔 {other.foreshadow_id} 真相相同，"
                            "可能是重复伏笔"
                        ),
                    }
                )

        if scenes and idx is not None:
            target = None
            for scene in scenes:
                scene_id = (
                    scene.get("scene_id")
                    if isinstance(scene, dict)
                    else getattr(scene, "scene_id", None)
                )
                if scene_id == fs.planted_in_scene:
                    target = scene
                    break
            if target is not None:
                present = set(
                    (
                        target.get("present_characters", [])
                        if isinstance(target, dict)
                        else getattr(target, "present_characters", [])
                    )
                    or []
                )
                for name in fs.visible_to:
                    if name in names and name not in present:
                        issues.append(
                            {
                                "severity": "minor",
                                "conflict": (
                                    f"{name} 未出现在埋设场景中，"
                                    "请确认其知情来源"
                                ),
                            }
                        )
        return issues

    def _build_foreshadow_conflict_prompt(
        self,
        project: NovelProject,
        fs: Foreshadowing,
        assembler: Optional[PromptContextAssembler] = None,
    ) -> str:
        query = f"{fs.description} {fs.target_revelation}"
        rag = (
            assembler.rag_context("director", query=query, k=6)
            if assembler is not None
            else (
                self.memory.retrieval_block(query, k=6, viewer="director")
                if self.memory is not None
                else ""
            )
        )
        payload = {
            "foreshadow": {
                "foreshadow_id": fs.foreshadow_id,
                "description": fs.description,
                "target_revelation": fs.target_revelation,
                "planted_in_scene": fs.planted_in_scene,
                "visible_to": fs.visible_to,
                "linked_characters": fs.linked_characters,
            },
            "project": {
                "scene_count": project.scene_count,
                "characters": [
                    {
                        "name": c.name,
                        "persona": c.persona,
                        "motivation": c.motivation,
                    }
                    for c in project.characters
                ],
                "locations": [
                    {"name": l.name, "description": l.description}
                    for l in project.locations
                ],
            },
            "existing_foreshadowings": [
                {
                    "foreshadow_id": f.foreshadow_id,
                    "description": f.description,
                    "target_revelation": f.target_revelation,
                    "status": f.status.value,
                    "planted_in_scene": f.planted_in_scene,
                    "visible_to": f.visible_to,
                }
                for f in project.foreshadowings
            ],
            "relevant_memories": rag,
        }
        return self.crew.task_prompt(
            "foreshadow_conflict",
            foreshadow_context=json.dumps(payload, ensure_ascii=False, indent=2),
        )

    async def check_foreshadow_conflicts(
        self,
        project: NovelProject,
        fs: Foreshadowing,
        scenes: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """回溯伏笔的结构检查 + 导演视角 LLM 一致性检查。"""
        issues = self._hardcode_foreshadow_checks(project, fs, scenes)
        idx = self._scene_index_of(fs.planted_in_scene)
        retroactive = idx is not None and idx < project.scene_count
        if not retroactive or self.crew is None:
            return issues

        # 伏笔冲突检查只需要 RAG，场景上下文留空即可
        assembler = PromptContextAssembler(
            memory=self.memory,
            project=project,
            scene_brief="",
            present_chars=[],
        )
        prompt = self._build_foreshadow_conflict_prompt(project, fs, assembler=assembler)
        raw = await self._kickoff(
            agent=self.crew.director(), prompt=prompt, timeout_s=60.0
        )
        if raw is None:
            issues.append(
                {
                    "severity": "minor",
                    "conflict": "LLM 一致性检查未执行（模型不可用或超时）",
                }
            )
            return issues
        try:
            payload = parse_json_block(raw)
        except Exception:
            issues.append(
                {
                    "severity": "minor",
                    "conflict": "LLM 一致性检查返回无法解析",
                }
            )
            return issues
        for conflict in payload.get("conflicts", []) or []:
            if not isinstance(conflict, dict):
                continue
            severity = conflict.get("severity", "minor")
            if severity not in ("major", "minor"):
                severity = "minor"
            issues.append(
                {
                    "severity": severity,
                    "conflict": str(conflict.get("conflict", "")),
                    "evidence": str(conflict.get("evidence", "")),
                }
            )
        return issues

    @staticmethod
    def _infer_delta(
        mode: Literal["director", "game"],
        scene_brief: str,
    ) -> StateDelta:
        """
        导演模式下从 scene_brief 推断 StateDelta（推 1 分钟 + 一条事件）。

        游戏模式 state_delta 由 GM 裁决产出，不走这里。
        """
        return StateDelta(
            time_delta=1,
            events=[
                WorldEvent(
                    kind="scene_start" if mode == "director" else "turn",
                    actor="narrator",
                    summary=scene_brief[:100],
                )
            ],
        )

    @staticmethod
    def _foreshadow_summary(project: NovelProject) -> str:
        """构造伏笔简要状态表（给 DirectorAgent 看）"""
        active = [
            f
            for f in project.foreshadowings
            if f.status in (ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED)
        ]
        if not active:
            return "（当前无活跃伏笔）"

        lines = []
        for f in active:
            dormant = f.scenes_since_last_mention
            max_d = f.max_dormant_scenes
            urgent = dormant >= max_d - 1
            tag = "🚨" if urgent else "  "
            lines.append(
                f"  {tag} [{f.foreshadow_id}] {f.description[:60]}"
                f"  | 沉睡 {dormant}/{max_d} 场景"
            )

        return "\n".join(lines)

    @staticmethod
    def _actor_log_from_pre_context(pre_context: Optional[Dict[str, Any]]) -> str:
        """游戏模式：从 GM 裁决结果构造 actor_log"""
        if not pre_context:
            return ""
        parts = []
        verdict = pre_context.get("gm_verdict", "")
        if verdict:
            parts.append(f"[GM 裁决] {verdict}")
        echo = pre_context.get("side_stage_echo")
        if echo:
            parts.append(str(echo))
        return "\n\n".join(parts)

    @staticmethod
    def _fallback_director_json(
        scene_brief: str, mode: Literal["director", "game"]
    ) -> Dict[str, Any]:
        """DirectorAgent LLM 不可用时的降级 JSON"""
        return {
            "surprise_idea": {
                "type": "none",
                "description": "",
                "should_happen": False,
                "severity": "none",
                "justification": "（LLM 不可用，降级处理）",
            },
            "director_intent": {
                "goal": scene_brief[:60] if scene_brief else "推进叙事",
                "tone": "neutral",
                "key_events": [],
                "do_not_happen": [],
            },
            "foreshadow_ops": [],
            "consistency": {
                "passed": True,
                "conflicts": [],
                "retry_suggestion": "",
            },
        }

    @staticmethod
    def _fallback_adjudicate(
        proposal: ActionProposal, state: WorldState
    ) -> AdjudicationResult:
        """无 LLM 时的最小兜底（搬自 turn_flow.py _fallback_adjudicate）"""
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

    def _npc_round_fallback(
        self, state: WorldState, exclude_actor: str
    ) -> StateDelta:
        """crew=None + idle_turns >= 3 时的硬编码 NPC 事件轮。

        搬自 turn_flow.py _npc_round 的 _fallback_npc 路径。
        """
        player = state.characters.get("玩家") or state.characters.get(exclude_actor)
        location = player.location if player else ""
        candidates = [
            name
            for name in state.characters_at(location)
            if name != exclude_actor
        ]
        if not candidates:
            return StateDelta()

        events: List[WorldEvent] = []
        for i, npc in enumerate(candidates[:2]):
            if i == 0:
                events.append(
                    WorldEvent(
                        kind="npc_action",
                        actor=npc,
                        summary=f"{npc} 走近了几步，环顾四周。",
                    )
                )
            else:
                events.append(
                    WorldEvent(
                        kind="npc_action",
                        actor=npc,
                        summary=f"{npc} 低声自语，似乎在等待什么。",
                    )
                )

        return StateDelta(time_delta=1, events=events)


    def _world_context(self, state: WorldState, actor: str) -> str:
        """构造渲染用世界书（搬自旧 TurnLoop）：以 state.view(actor) 为唯一数据源。

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

        # —— 事实：按 visible_to 过滤后的条目 ——
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


# ---------------------------------------------------------------------------
# memory_facts 消费：把 Agent 在 JSON 里附带的预压缩记忆写入 memory 层
# ---------------------------------------------------------------------------

_VALID_TIERS = frozenset({"short_term"})


def _apply_memory_facts(
    *,
    memory: LayeredMemory,
    facts: Any,
    scene_index: int,
    prose: str,
    brief: str,
    present_chars: List[str],
) -> None:
    """优先用 Agent 预压缩的 memory_facts 写入；缺省时回退到 add_scene。

    调用次数不增加——memory_facts 就是同一次 JSON 输出的一部分。
    每条 fact 的 text 必须是压缩好的最终形态，长度 ≤ MEMORY_ITEM_MAX_CHARS。
    文言存储模式下必须同时提供 display_text（白话版）；缺少时跳过该条，
    避免文言文出现在玩家 / 导演界面。
    """
    classical = memory.settings.classical_compression
    valid_facts = []
    if isinstance(facts, list):
        for item in facts:
            if not isinstance(item, dict):
                continue
            tier = str(item.get("tier") or "short_term")
            text = str(item.get("text") or "").strip()
            display = str(item.get("display_text") or "").strip()
            if not text or tier not in _VALID_TIERS:
                continue
            if len(text) > MEMORY_ITEM_MAX_CHARS:
                # 超长 fact 直接跳过——Agent 没做好压缩，memory 层也不切
                continue
            if len(display) > MEMORY_ITEM_MAX_CHARS:
                continue
            if classical and not display:
                # 文言模式缺少白话展示版 → 回退到 add_scene 处理 prose
                continue
            valid_facts.append((item, display))

    if valid_facts:
        for fact, display in valid_facts:
            memory.add_condensed(
                tier=str(fact.get("tier") or "short_term"),
                text=str(fact.get("text") or "").strip(),
                display_text=display or None,
                scene_index=scene_index,
                visible_to=[
                    str(v).strip()
                    for v in (fact.get("visible_to") or [])
                    if str(v).strip()
                ]
                or None,
                tags=[
                    str(v).strip()
                    for v in (fact.get("tags") or [])
                    if str(v).strip()
                ] or None,
                source="agent_memory_fact",
                consolidate=False,
            )
        # 同一回合的多条 fact 只整理一次，避免逐条触发压缩
        memory.consolidate()
        return

    # 没有 memory_facts（老 Agent 输出 / LLM 不可用）：回退到 add_scene。
    # add_scene 内部会对 prose 做 summarize 入库，不会直接存原文。
    memory.add_scene(
        scene_index=scene_index,
        prose=prose,
        brief=brief,
        present_characters=present_chars,
    )


__all__ = [
    "AdvanceResult",
    "NarrateResult",
    "NarrativeEngine",
    "SceneResult",
    "TurnBoot",
    "TurnResult",
    "advance_scene_counters",
    "apply_foreshadow_ops",
    "parse_json_block",
]
