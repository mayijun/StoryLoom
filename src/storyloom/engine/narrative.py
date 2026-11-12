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
                visibility=new_data.get("visibility", "restricted"),
                known_by=new_data.get("known_by", []),
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
    ) -> SceneResult:
        """
        导演模式入口：生成一个完整场景。

        流程：
          _narrate(mode="director", enable_crew=True)
          → _advance_world(mode="director")
          → 返回 SceneResult(prose, director_json, project, world_state)
        """
        narrate_result = await self._narrate(
            project=project,
            scene_brief=scene_brief,
            present_chars=present_chars,
            mode="director",
            pre_context=None,
            enable_crew=True,
            enable_consistency=True,
            max_retries=max_retries,
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
                proposal=proposal, state=world_state, mode=mode, frame=arc_frame,
            )
            pre_context_gm = {
                "gm_verdict": adjudication.narrative,
                "player_success": adjudication.success,
                "outcome": adjudication.outcome,
            }

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
            quality=1.0,
            quality_flags=[] if (adjudication is None or adjudication.success) else ["rejected"],
            frame=arc_result,
            log={
                "elapsed_ms": elapsed_ms,
                "scene_count": project.scene_count,
            },
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
        # ---- Step 1: DirectorAgent kickoff ----
        director_json = {}
        for attempt in range(max_retries + 1):
            # crew 不可用 → 硬编码降级
            if self.crew is None:
                director_json = self._fallback_director_json(scene_brief, mode)
                break

            director_prompt = self._build_director_prompt(
                project=project,
                scene_brief=scene_brief,
                present_chars=present_chars,
                mode=mode,
                pre_context=pre_context,
            )
            raw = await self._kickoff(
                agent=self.crew.director(),
                prompt=director_prompt,
                timeout_s=90.0,
            )
            if raw is None:
                # LLM 不可用 → 用降级 JSON
                director_json = self._fallback_director_json(scene_brief, mode)
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
                if attempt < max_retries:
                    print(
                        f"  ⚠️ DirectorAgent 一致性 major 冲突，"
                        f"retry {attempt + 1}/{max_retries}..."
                    )
                    continue
            break

        if not director_json:
            director_json = self._fallback_director_json(scene_brief, mode)

        # ---- Step 2: 动态 Crew（option） ----
        actor_log = ""
        rag_context = (
            self.memory.retrieval_block(
                scene_brief, k=3, viewer="director"
            )
            if self.memory
            else ""
        )

        if enable_crew and mode == "director" and self.crew is not None:
            actor_log = await self._run_dynamic_crew(
                project=project,
                present_chars=present_chars,
                director_json=director_json,
                rag_context=rag_context,
                memory_query=scene_brief,
            )
        else:
            # 游戏模式、禁用 Crew、或 crew 不可用 → actor_log 直接从 pre_context 取
            actor_log = self._actor_log_from_pre_context(pre_context)

        # ---- Step 3: ProseAgent kickoff ----
        prose = ""
        choices: List[Dict[str, Any]] = []

        # crew 不可用 → 直接用 scene_brief 作为 prose
        if self.crew is None:
            prose = scene_brief or (pre_context or {}).get("gm_verdict", "")
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
                timeout_s=90.0,
            )
            if raw_prose is not None:
                packet = parse_agent_packet(raw_prose)
                prose = packet.prose or raw_prose.strip()
                choices = [
                    {"text": c.text, "hint": c.hint} for c in packet.choices
                ]

        return NarrateResult(
            director_json=director_json,
            actor_log=actor_log,
            prose=prose,
            choices=choices,
            consistency_issues=self._hardcode_checks(director_json, project, mode),
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

        # 3. memory.add_scene（两种模式都调，但 memory=None 时跳过）
        scene_idx = project.scene_count
        if memory is not None:
            memory.add_scene(
                scene_index=scene_idx,
                prose=prose,
                brief=scene_brief,
                present_characters=present_chars,
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

        prompt = self._crew_adjudication_prompt(proposal, state, mode, frame)
        raw = await self._kickoff(
            agent=self.crew.director(), prompt=prompt, timeout_s=60.0
        )
        if raw is None:
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
        project: NovelProject,
        scene_brief: str,
        present_chars: List[str],
        mode: Literal["director", "game"],
        pre_context: Optional[Dict[str, Any]],
    ) -> str:
        """构造 DirectorAgent 的提示词"""
        # memory 上下文
        if self.memory is not None:
            memory_block = self.memory.prompt_block(viewer="director")
            rag_context = self.memory.retrieval_block(
                scene_brief, k=3, viewer="director"
            )
        else:
            memory_block = ""
            rag_context = ""

        # 资产层简要
        char_names = [c.name for c in project.characters]
        char_brief = (
            "\n".join(
                f"- {c.name}（{c.importance_tier}）：{c.persona[:60]}"
                for c in project.characters[:6]
            )
            if project.characters
            else "（无角色配置）"
        )
        loc_brief = (
            ", ".join(l.name for l in project.locations[:6])
            if project.locations
            else "（无地点配置）"
        )

        # 伏笔简要状态表（DirectorAgent 可以看简要表，详情用 tool 查）
        foreshadow_table = self._foreshadow_summary(project)

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
            pre_context_str = (
                "\n\n【GM 裁决结果】（仅游戏模式有）\n"
                f"裁决叙事: {pre_context.get('gm_verdict', '')}\n"
                f"玩家是否成功: {'是' if pre_context.get('player_success') else '否'}\n"
                f"结局类型: {pre_context.get('outcome', '')}\n"
            )

        extension_block = ""
        if self.extensions is not None:
            skill_text = self.extensions.skill_prompt()
            rules = self.extensions.rules()
            if skill_text:
                extension_block += f"\n【扩展设定】\n{skill_text}\n"
            if rules:
                extension_block += (
                    "\n【扩展规则】\n"
                    + json.dumps(rules, ensure_ascii=False, indent=2)
                    + "\n"
                )

        return (
            "你是本作导演兼创作总指挥。\n"
            f"{mode_hint}\n"
            "\n"
            f"【已出场角色】: {', '.join(present_chars)}\n"
            f"【全部角色一览】:\n{char_brief}\n"
            f"【地点一览】: {loc_brief}\n"
            f"【scene_brief/玩家行动】: {scene_brief}\n"
            "\n"
            f"【记忆工作区】:\n{memory_block}\n"
            f"【RAG 检索】:\n{rag_context}\n"
            f"【伏笔简要状态表】:\n{foreshadow_table}\n"
            f"{pre_context_str}\n"
            f"{extension_block}\n"
            "\n"
            "请输出一个 JSON 对象（不要 Markdown 代码围栏），"
            "包含以下四个部分：\n"
            "{\n"
            '  "surprise_idea": { "type": "...", "description": "...", '
            '"should_happen": true, "severity": "minor|moderate|major", '
            '"justification": "..." },\n'
            '  "director_intent": { "goal": "...", "tone": "...", '
            '"key_events": ["..."], "do_not_happen": ["..."] },\n'
            '  "foreshadow_ops": [ { "action": "plant|reinforce|resolve|subvert", ... } ],\n'
            '  "consistency": { "passed": true, "conflicts": [], "retry_suggestion": "" }\n'
            "}\n"
            "\n"
            "foreshadow_ops 里每个操作的格式：\n"
            "- plant: {\"action\":\"plant\",\"new_foreshadow\":{\"description\":\"...\",\"linked_characters\":[...],\"target_revelation\":\"...\",\"visibility\":\"restricted|public\",\"known_by\":[...]}}\n"
            "- reinforce/resolve/subvert: {\"action\":\"...\",\"foreshadow_id\":\"fs_xxx\"}\n"
            "没有伏笔要操作时 foreshadow_ops 填空数组。\n"
            "consistency 里自检人设/时间线/设定冲突；major 冲突把 severity 标记在 conflicts 里。"
            "需要查看伏笔详细状态时，调用 query_active_foreshadows tool。"
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

        return (
            f"{PACKET_CONTRACT}\n\n"
            f"你是本作的润色 Agent，把下面的行动日志写成流畅的中文叙事。\n"
            f"{output_hint}\n\n"
            f"【导演意图】:\n{intent_str}\n\n"
            f"【角色互动日志】:\n{actor_log or '（无角色互动，直接进入叙事）'}\n\n"
            f"【文风偏好】: {style or '（默认细腻文风）'}\n\n"
            "请只填写 prose（导演模式）或 prose + choices（游戏模式）字段。"
        )

    async def _run_dynamic_crew(
        self,
        *,
        project: NovelProject,
        present_chars: List[str],
        director_json: Dict[str, Any],
        rag_context: str,
        memory_query: str = "",
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

        agents: List[Agent] = []
        tasks: List[Task] = []

        intent_str = json.dumps(
            director_json.get("director_intent", {}),
            ensure_ascii=False,
            indent=2,
        )

        def char_memory(char) -> tuple[str, str]:
            if not self.memory:
                return "", rag_context
            return (
                self.memory.prompt_block(viewer=char.name),
                self.memory.retrieval_block(
                    memory_query, k=3, viewer=char.name
                ),
            )

        for char in primary_chars:
            agent = self.crew.protagonist(char)
            memory_block, char_rag = char_memory(char)
            agents.append(agent)
            tasks.append(
                Task(
                    description=(
                        f"请以【{char.name}】的身份，给出这一刻的"
                        f"内心想法、台词和行动。\n"
                        f"简洁、符合人设，只写行动日志式的描述。"
                        f"\n\n导演意图:\n{intent_str}\n\n"
                        f"RAG 上下文:\n{char_rag}\n\n"
                        f"记忆:\n{memory_block}\n"
                    ),
                    expected_output=(
                        f"{char.name} 的行动日志片段（3~5 句），"
                        f"描述想法、台词、行动"
                    ),
                    agent=agent,
                )
            )

        if secondary_chars:
            ensemble = self.crew.ensemble(secondary_chars)
            agents.append(ensemble)
            for char in secondary_chars:
                memory_block, char_rag = char_memory(char)
                tasks.append(
                    Task(
                        description=(
                            f"现在请代入次要角色【{char.name}】。\n"
                            f"只写这一个角色的台词与动作，"
                            f"不要替其他角色发言。\n"
                            f"给出{char.name}在这一刻的简短反应/台词。"
                            f"\n\n导演意图:\n{intent_str}\n\n"
                            f"RAG:\n{char_rag}\n\n"
                            f"记忆:\n{memory_block}\n"
                        ),
                        expected_output=(
                            f"{char.name} 的简短行动描述（1~2 句）"
                        ),
                        agent=ensemble,
                    )
                )

        if not agents:
            # 没有出场角色 → 跳过 Crew
            intent = director_json.get("director_intent", {})
            return f"（无角色互动）导演意图: {intent.get('goal', '')}"

        crew = Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
        )

        loop = asyncio.get_event_loop()

        def _sync_kickoff() -> Any:
            return crew.kickoff()

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_kickoff), timeout=120.0
            )
            return str(result).strip() if result else ""
        except asyncio.TimeoutError:
            print("  ⏱️ 动态 Crew kickoff 超时，跳过角色互动")
            return ""
        except Exception as exc:
            print(f"  ⚠️ 动态 Crew kickoff 失败: {exc}")
            return ""

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
        for name in fs.known_by:
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
                for name in fs.known_by:
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
        self, project: NovelProject, fs: Foreshadowing
    ) -> str:
        rag = ""
        if self.memory is not None:
            rag = self.memory.retrieval_block(
                f"{fs.description} {fs.target_revelation}",
                k=6,
                viewer="director",
            )
        payload = {
            "foreshadow": {
                "foreshadow_id": fs.foreshadow_id,
                "description": fs.description,
                "target_revelation": fs.target_revelation,
                "planted_in_scene": fs.planted_in_scene,
                "visibility": fs.visibility,
                "known_by": fs.known_by,
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
                    "known_by": f.known_by,
                }
                for f in project.foreshadowings
            ],
            "relevant_memories": rag,
        }
        return (
            "你是小说的世界观一致性审校员。作者准备回溯插入一条伏笔："
            "它埋设在过去，但在已有正文中可能没有提到。\n"
            "请检查这条伏笔的描述、真相、知情角色是否与已有角色设定、"
            "历史场景记忆、世界书条目或其它伏笔冲突。\n"
            "只输出 JSON，不要 Markdown 代码围栏：\n"
            '{"passed": true, "conflicts": '
            '[{"severity": "major|minor", "conflict": "...", '
            '"evidence": "..."}]}\n'
            "没有冲突时 conflicts 为空数组。\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
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

        prompt = self._build_foreshadow_conflict_prompt(project, fs)
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
        verdict = pre_context.get("gm_verdict", "")
        return f"[GM 裁决] {verdict}"

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

    def _crew_adjudication_prompt(
        self,
        proposal: ActionProposal,
        state: WorldState,
        mode: Literal["game", "director"],
        frame: Optional[DirectorFrame] = None,
    ) -> str:
        """GM 裁决的提示词（搬自 crew.py _adjudication_prompt）"""
        goal = getattr(frame, "goal", "") if frame is not None else ""
        phase = getattr(frame, "phase", "") if frame is not None else ""
        mode_rule = (
            "导演模式：这是作者指令，decision 用 direct，不要否决。"
            if mode == "director"
            else "游戏模式：世界先于玩家，不可行的行动用 reject。"
        )
        world_brief = SceneCrew._world_brief(state, proposal.actor)
        return (
            "你是本作导演兼世界裁决者。"
            f"{mode_rule}\n"
            f"{PACKET_CONTRACT}\n"
            f"当前节拍：{phase}；叙事目标：{goal or '（未指定）'}\n"
            f"世界状态：\n{world_brief}\n"
            f"行动者：{proposal.actor}\n"
            f"行动：{proposal.detail or proposal.kind}\n"
            f"目标：{proposal.target or '（无）'}\n"
            "请裁决该行动是否发生，并只填写 decision / narrative / reason / "
            "state / available 字段。state 只写必要变化，"
            "没有变化时至少给出 time_delta。"
        )

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
