"""
CrewAI引擎桥接：连接FastAPI和已有的CrewAI多Agent后端
"""

import json
import asyncio
import time
from typing import List, Optional
from pathlib import Path

from dotenv import load_dotenv

# 必须在创建 ModelRegistry/Router 之前加载根目录 .env
# （router.is_available 依赖环境变量中的 API Key）
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from storyloom.llm.providers import ModelRegistry
from storyloom.llm.router import AgentModelRouter
from storyloom.crews.scene_crew.crew import SceneCrew
from storyloom.db import DEFAULT_PROJECT_ID, get_repository
from storyloom.models import (
    CharacterAsset,
    ForeshadowStatus,
    LocationAsset,
    NovelProject,
    Foreshadowing,
)

# 伏笔显式状态机：action → (允许的前置状态, 目标状态)
_FORESHADOW_TRANSITIONS: dict[str, tuple[set[ForeshadowStatus], ForeshadowStatus]] = {
    "reinforce": (
        {ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED},
        ForeshadowStatus.REINFORCED,
    ),
    "activate": (
        {ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED},
        ForeshadowStatus.ACTIVATED,
    ),
    "resolve": (
        {ForeshadowStatus.ACTIVATED},
        ForeshadowStatus.RESOLVED,
    ),
    "subvert": (
        {
            ForeshadowStatus.PLANTED,
            ForeshadowStatus.REINFORCED,
            ForeshadowStatus.ACTIVATED,
        },
        ForeshadowStatus.SUBVERTED,
    ),
    "abandon": (
        {
            ForeshadowStatus.PLANTED,
            ForeshadowStatus.REINFORCED,
            ForeshadowStatus.ACTIVATED,
        },
        ForeshadowStatus.ABANDONED,
    ),
    "replant": (
        {
            ForeshadowStatus.RESOLVED,
            ForeshadowStatus.SUBVERTED,
            ForeshadowStatus.ABANDONED,
        },
        ForeshadowStatus.PLANTED,
    ),
}
from storyloom.memory import (
    CoreMemory,
    LayeredMemory,
    MemoryIndexer,
    MemorySettings,
    SimpleRAGMemory,
)
from storyloom.flows.scene_flow import SceneGenerationFlow
from storyloom.flows.turn_flow import TurnBoot, TurnLoop, TurnResult
from storyloom.extensions.host import ExtensionRegistry
from storyloom.runtime.directive import StageDirective, StageScene
from storyloom.runtime.intent import PlayerIntent
from storyloom.runtime.renderer import SceneRenderer
from storyloom.saves.service import SaveService, state_from_save
from storyloom.world.authority import AuthorityController
from storyloom.world.game_master import AdjudicationResult
from storyloom.world.state import StateDelta, WorldState
from storyloom.api.schemas import (
    GenerateSceneRequest, GenerationStepUpdate,
    GenerateSceneResponse, ForeshadowingView,
)

def _deep_merge(base: dict, patch: dict) -> dict:
    """递归合并配置补丁：字典逐层合并，其他类型直接覆盖"""
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class NovelEngine:
    """
    小说引擎：封装CrewAI后端，提供API友好的接口
    支持多项目管理和SSE实时推送

    项目元数据落库（SQLite/PostgreSQL，projects 表），
    Agent / Task 配置也从属于项目（外键引用），
    运行时状态（characters / foreshadowings）暂存内存，
    重启后重新进入项目时会从 DB 元数据重建。
    """

    def __init__(self):
        self.registry = ModelRegistry()
        self.router = AgentModelRouter(self.registry)
        # 每个小说项目拥有独立的 Agent / Task 配置，因此按项目缓存 Crew
        self.crews: dict[str, SceneCrew] = {}
        self.crew = self._crew_for(DEFAULT_PROJECT_ID)

        self.memories: dict[str, CoreMemory] = {}
        self.rags: dict[str, SimpleRAGMemory] = {}
        # 运行时 NovelProject 对象缓存（元数据落库，运行时状态暂存内存）
        self._project_runtime: dict[str, NovelProject] = {}

        # 双模式运行时（M0）：WorldState 不落 DB，仅按实例暂存
        self.game_states: dict[tuple[str, str], WorldState] = {}
        self.game_memories: dict[str, LayeredMemory] = {}
        self.last_turns: dict[tuple[str, str], TurnResult] = {}
        self.save_service = SaveService()
        self.extension_registry = ExtensionRegistry()

        repo = get_repository()
        # 确保所有旧库数据、默认项目都已在 projects 表里
        repo.create_all()
        repo.ensure_project(DEFAULT_PROJECT_ID)

        # 如果 projects 表完全空（全新库），写入示例项目
        if not repo.list_projects():
            repo.create_project(
                DEFAULT_PROJECT_ID,
                "示例项目 · 快速上手",
                "film_narrative",
            )

        # 为所有已存项目预播种默认 Agent / Task 配置（若尚未播种）
        for proj in repo.list_projects():
            repo.ensure_seeded(proj["project_id"])

        # 试用模板改为用户在 Web 界面主动选择「试用模板」时应用，
        # 不再开机自动播种，避免占用数据库且便于试用后清理。
        # 模板内嵌的扩展（map / skill）由 ExtensionRegistry 在首次解析时加载。

    # ---------------- 项目管理 ----------------

    def _build_project(self, meta: dict) -> NovelProject:
        """从 projects 表的元数据构造 NovelProject 运行时对象，
        并从 DB 加载已落库的角色 / 场景 / 伏笔。"""
        repo = get_repository()
        project = NovelProject(
            project_id=meta["project_id"],
            title=meta["title"],
            style=meta["style"],
            characters=[
                CharacterAsset(
                    name=c["name"],
                    importance_tier=c["importance_tier"],
                    persona=c["persona"],
                    motivation=c["motivation"],
                    secrets=c.get("secrets", ""),
                )
                for c in repo.list_characters(meta["project_id"])
            ],
            locations=[
                LocationAsset(
                    name=l["name"], description=l.get("description", "")
                )
                for l in repo.list_locations(meta["project_id"])
            ],
            description=meta.get("description", "") or "",
        )
        project.scene_count = meta["scene_count"]
        project.foreshadowings = [
            Foreshadowing(
                foreshadow_id=f["foreshadow_id"],
                description=f["description"],
                planted_in_scene=f["planted_in_scene"],
                target_revelation=f["target_revelation"],
                status=f["status"],
                reinforcement_count=f["reinforcement_count"],
                max_dormant_scenes=f["max_dormant_scenes"],
                scenes_since_last_mention=f["scenes_since_last_mention"],
                linked_characters=list(f.get("linked_characters", [])),
                linked_surprise_ids=list(f.get("linked_surprise_ids", [])),
            )
            for f in repo.list_foreshadowings(meta["project_id"])
        ]
        return project

    def _get_or_load_project(self, project_id: str) -> NovelProject:
        """获取运行时 NovelProject；若缓存未命中则从 DB 元数据重建"""
        cached = self._project_runtime.get(project_id)
        if cached is not None:
            return cached
        repo = get_repository()
        meta = repo.get_project(project_id)
        if meta is None:
            raise KeyError(f"项目不存在: {project_id}")
        project = self._build_project(meta)
        self._project_runtime[project_id] = project
        # 同步内存存储（兼容旧代码路径）
        self.memories.setdefault(project_id, CoreMemory())
        self.rags.setdefault(project_id, SimpleRAGMemory(project_id))
        return project

    # 兼容旧代码：engine.projects['demo'] 仍可访问（只读快照）
    @property
    def projects(self) -> dict:
        """
        返回项目 ID → NovelProject 的映射快照（供旧代码路径访问）。
        写入请用 create_project / add_character 等方法，它们会同时落库。
        """
        repo = get_repository()
        result: dict[str, NovelProject] = {}
        for meta in repo.list_projects():
            pid = meta["project_id"]
            cached = self._project_runtime.get(pid)
            result[pid] = cached or self._build_project(meta)
        return result

    def _crew_for(self, project_id: str) -> SceneCrew:
        """获取（或创建）某个小说项目专属的 Crew 实例"""
        crew = self.crews.get(project_id)
        if crew is None:
            crew = SceneCrew(self.router, project_id=project_id)
            self.crews[project_id] = crew
        return crew

    def get_available_models(self) -> List[str]:
        return self.registry.list_available()

    def create_project(
        self, project_id: str, title: str, style: str, description: str = ""
    ) -> NovelProject:
        """创建项目（落库），并为其播种一套默认 Agent / Task"""
        repo = get_repository()
        try:
            repo.create_project(project_id, title, style, description)
        except ValueError:
            # 已存在：直接加载元数据
            repo.upsert_project(project_id, title=title, style=style, description=description)

        project = self._build_project(repo.get_project(project_id))
        self._project_runtime[project_id] = project
        self.memories[project_id] = CoreMemory()
        self.rags[project_id] = SimpleRAGMemory(project_id)
        return project

    def get_project(self, project_id: str) -> NovelProject | None:
        repo = get_repository()
        if not repo.project_exists(project_id):
            return None
        return self._get_or_load_project(project_id)

    def list_projects(self) -> list[dict]:
        """返回 projects 表的元数据（用于 API 列表）"""
        return get_repository().list_projects()

    # ---------------- 试用模板 ----------------

    def list_templates(self) -> list[dict]:
        """列出所有可用的试用模板摘要。"""
        from storyloom.templates import list_templates

        return list_templates()

    def apply_template(self, template_id: str, title: str | None = None) -> dict:
        """应用一个试用模板，生成一个新项目并返回其元数据。

        项目 id 形如 ``tpl_<template_id>_<8hex>``，是普通项目，
        用户试用后可直接删除以清理。模板内嵌的扩展会注册到全局
        ExtensionRegistry（若尚未注册）。
        """
        import uuid

        from storyloom.templates import apply_template as _apply

        repo = get_repository()
        project_id = f"tpl_{template_id}_{uuid.uuid4().hex[:8]}"
        _apply(
            template_id,
            project_id,
            repo,
            title=title,
            extension_registry=self.extension_registry,
        )
        # 同步运行时缓存
        meta = repo.get_project(project_id)
        self._project_runtime[project_id] = self._build_project(meta)
        self.memories[project_id] = CoreMemory()
        self.rags[project_id] = SimpleRAGMemory(project_id)
        return meta

    def add_character(self, project_id, char: CharacterAsset):
        project = self._get_or_load_project(project_id)
        # 先落库（upsert：重名则更新）
        get_repository().upsert_character(
            project_id,
            name=char.name,
            importance_tier=char.importance_tier,
            persona=char.persona,
            motivation=char.motivation,
            secrets=char.secrets,
        )
        # 同步内存：若已存在则替换，否则追加
        project.characters = [
            c for c in project.characters if c.name != char.name
        ] + [char]
        get_repository().update_project_stats(
            project_id, character_count=len(project.characters)
        )
        self.rags[project_id].add(
            f"char_{char.name}",
            f"{char.name}: {char.persona}. 动机: {char.motivation}",
            {"type": "character"},
        )

    def add_location(self, project_id, loc: LocationAsset):
        project = self._get_or_load_project(project_id)
        get_repository().upsert_location(
            project_id, name=loc.name, description=loc.description
        )
        project.locations = [
            l for l in project.locations if l.name != loc.name
        ] + [loc]
        self.rags[project_id].add(
            f"loc_{loc.name}",
            f"{loc.name}: {loc.description}",
            {"type": "location"},
        )

    def add_foreshadowing(self, project_id, fs: Foreshadowing):
        project = self._get_or_load_project(project_id)
        get_repository().upsert_foreshadowing(
            project_id,
            foreshadow_id=fs.foreshadow_id,
            description=fs.description,
            planted_in_scene=fs.planted_in_scene,
            target_revelation=fs.target_revelation,
            status=fs.status.value,
            reinforcement_count=fs.reinforcement_count,
            max_dormant_scenes=fs.max_dormant_scenes,
            scenes_since_last_mention=fs.scenes_since_last_mention,
            linked_characters=fs.linked_characters,
            linked_surprise_ids=fs.linked_surprise_ids,
        )
        project.foreshadowings = [
            f for f in project.foreshadowings
            if f.foreshadow_id != fs.foreshadow_id
        ] + [fs]
        get_repository().update_project_stats(
            project_id, foreshadowing_count=len(project.foreshadowings)
        )

    def transition_foreshadowing(
        self, project_id: str, foreshadow_id: str, action: str
    ) -> Foreshadowing:
        """伏笔状态显式流转（作者在 UI 上手动推进状态机）。

        校验前置状态合法性后更新内存对象并落库。
        非法流转抛 ValueError，未找到伏笔抛 KeyError。
        """
        project = self._get_or_load_project(project_id)
        fs = next(
            (f for f in project.foreshadowings
             if f.foreshadow_id == foreshadow_id),
            None,
        )
        if fs is None:
            raise KeyError(f"伏笔不存在: {foreshadow_id}")
        if action not in _FORESHADOW_TRANSITIONS:
            raise ValueError(f"未知的伏笔操作: {action}")

        allowed_from, target = _FORESHADOW_TRANSITIONS[action]
        if fs.status not in allowed_from:
            raise ValueError(
                f"伏笔当前状态为 {fs.status.value}，"
                f"不允许执行 {action}（允许的前置状态: "
                f"{sorted(s.value for s in allowed_from)}）"
            )

        fs.status = target
        fs.scenes_since_last_mention = 0
        if action == "reinforce":
            fs.reinforcement_count += 1
        elif action == "replant":
            fs.reinforcement_count = 0

        self._persist_foreshadowing(project_id, fs)
        return fs

    def _persist_foreshadowing(self, project_id: str, fs: Foreshadowing):
        get_repository().upsert_foreshadowing(
            project_id,
            foreshadow_id=fs.foreshadow_id,
            description=fs.description,
            planted_in_scene=fs.planted_in_scene,
            target_revelation=fs.target_revelation,
            status=fs.status.value,
            reinforcement_count=fs.reinforcement_count,
            max_dormant_scenes=fs.max_dormant_scenes,
            scenes_since_last_mention=fs.scenes_since_last_mention,
            linked_characters=fs.linked_characters,
            linked_surprise_ids=fs.linked_surprise_ids,
        )

    def delete_foreshadowing(self, project_id, foreshadow_id: str) -> bool:
        project = self._get_or_load_project(project_id)
        ok = get_repository().delete_foreshadowing(foreshadow_id, project_id)
        if ok:
            project.foreshadowings = [
                f for f in project.foreshadowings
                if f.foreshadow_id != foreshadow_id
            ]
            get_repository().update_project_stats(
                project_id,
                foreshadowing_count=len(project.foreshadowings),
            )
        return ok

    async def generate_scene(
        self,
        request: GenerateSceneRequest,
        scene_id: Optional[str] = None,
    ) -> GenerateSceneResponse:
        """生成场景（同步执行，异步包装）。

        scene_id 不为空时表示**重跑**已有场景：用传入的 scene_id 覆盖正文，
        不递增 scene_count。
        """
        project = self._get_or_load_project(request.project_id)
        memory = self.memories[request.project_id]
        rag = self.rags[request.project_id]
        crew = self._crew_for(request.project_id)

        # 更新在场角色
        memory.characters_present = request.present_character_names

        flow = SceneGenerationFlow(
            project=project,
            memory=memory,
            rag=rag,
            crew=crew,
            scene_brief=request.scene_brief,
            present_characters=request.present_character_names,
            is_regenerate=scene_id is not None,
        )
        flow.render_mode = request.render_mode

        # 在线程池中执行（CrewAI kickoff 是同步的）
        loop = asyncio.get_event_loop()
        started = time.perf_counter()
        final_text = await loop.run_in_executor(None, flow.kickoff)
        duration_ms = int((time.perf_counter() - started) * 1000)

        # 质量分：由一致性报告与重试次数确定性推导（0~1）
        report = flow.state.consistency_report
        quality_score = 1.0
        if report is not None:
            if not report.passed:
                quality_score = {"minor": 0.7, "major": 0.4}.get(
                    report.severity, 0.5
                )
            elif report.severity == "minor":
                quality_score = 0.85
        quality_score = max(
            0.0, round(quality_score - 0.1 * flow.state.retry_count, 2)
        )

        repo = get_repository()
        model_usage = dict(crew._summary) if hasattr(crew, "_summary") else {}

        # 重跑：用原 scene_id 覆盖；新建：用 scene_count 生成新编号
        if scene_id is not None:
            target_scene_id = scene_id
            repo.update_scene(
                target_scene_id,
                chapter_id=request.chapter_id,
                brief=request.scene_brief,
                present_characters=request.present_character_names,
                prose=str(final_text),
                quality_score=quality_score,
                duration_ms=duration_ms,
                model_usage=model_usage,
            )
        else:
            # scene_flow 在 kickoff 内部已经 project.scene_count += 1；
            target_scene_id = f"scene_{project.scene_count}"
            try:
                repo.create_scene(
                    scene_id=target_scene_id,
                    project_id=request.project_id,
                    chapter_id=request.chapter_id,
                    brief=request.scene_brief,
                    present_characters=request.present_character_names,
                    prose=str(final_text),
                    quality_score=quality_score,
                    duration_ms=duration_ms,
                    model_usage=model_usage,
                )
            except ValueError:
                # scene_id 已存在（极端情况）→ 覆盖
                repo.update_scene(
                    target_scene_id,
                    chapter_id=request.chapter_id,
                    brief=request.scene_brief,
                    present_characters=request.present_character_names,
                    prose=str(final_text),
                    quality_score=quality_score,
                    duration_ms=duration_ms,
                    model_usage=model_usage,
                )

        # 同步生成过程中可能变更的伏笔状态到 DB
        for fs in project.foreshadowings:
            self._persist_foreshadowing(request.project_id, fs)

        # 把更新后的统计写回数据库，保证下次重启仍能看到最新值
        repo.update_project_stats(
            request.project_id,
            scene_count=project.scene_count,
            character_count=len(project.characters),
            foreshadowing_count=len(project.foreshadowings),
        )

        # ------- 同步到分层记忆（LayeredMemory）-------
        # 导演写作流程用 CoreMemory 供 CrewAI 拼 prompt，
        # 但游戏模式 / 记忆面板读 LayeredMemory（game_memories）。
        # 这里把本次生成结果追加到 LayeredMemory，保证两套记忆互通，
        # 玩家切回游戏模式时能看到刚写的那幕。
        try:
            layer = self.memory_for(request.project_id)
            layer.add_scene(
                scene_index=project.scene_count if not scene_id else int(scene_id.split("_")[-1]),
                prose=str(final_text),
                brief=request.scene_brief,
                present_characters=request.present_character_names,
                active_foreshadow=bool(project.foreshadowings),
                key=target_scene_id,
            )
        except Exception as exc:  # noqa: BLE001
            # 记忆同步属于附加功能，失败不应阻断主流程
            print(f"  ℹ️ 分层记忆同步跳过: {exc}")

        # 构建伏笔视图
        fs_views = [
            ForeshadowingView(
                foreshadow_id=f.foreshadow_id,
                description=f.description,
                status=f.status.value,
                planted_in_scene=f.planted_in_scene,
                target_revelation=f.target_revelation,
                reinforcement_count=f.reinforcement_count,
                scenes_since_last_mention=f.scenes_since_last_mention,
                max_dormant_scenes=f.max_dormant_scenes,
                linked_characters=f.linked_characters,
            )
            for f in project.foreshadowings
        ]

        # 构建Agent创建摘要
        steps = [
            GenerationStepUpdate(
                step=f"agent_{i}",
                status="completed",
                agent_name=aid,
                agent_type=aid.split(":")[0],
                model_used=mkey,
            )
            for i, (aid, mkey) in enumerate(crew._summary)
        ]

        return GenerateSceneResponse(
            scene_id=target_scene_id,
            final_prose=str(final_text),
            steps=steps,
            foreshadowing_updates=fs_views,
        )


    # ================================================================
    # 双模式运行时（M0）
    # ================================================================

    def _memory_settings_for(self, project_id: str) -> MemorySettings:
        """从数据库读取项目级记忆配置（首次访问自动播种 YAML 默认值）"""
        return MemorySettings.from_dict(
            get_repository().load_memory_config(project_id)
        )

    def memory_for(
        self,
        project_id: str,
        backend: str | None = None,
    ) -> LayeredMemory:
        """项目级分层记忆：首次访问自动从历史场景与资产回填"""
        cached = self.game_memories.get(project_id)
        if cached is not None and (
            backend is None or cached.backend_name == backend
        ):
            return cached

        project = self._get_or_load_project(project_id)
        repo = get_repository()
        memory = LayeredMemory(
            project_id,
            repo=repo,
            settings=self._memory_settings_for(project_id),
            backend=backend,
            compress_fn=self._memory_compress_fn,
        )
        MemoryIndexer(memory).backfill(
            repo.list_scenes(project_id),
            project.characters,
            project.locations,
        )
        if cached is not None:
            memory.configure_working(
                location=cached.working.location,
                present_characters=cached.working.present_characters,
                scene_brief=cached.working.scene_brief,
                intent=cached.working.intent,
                time=cached.working.time,
            )
        self.game_memories[project_id] = memory
        return memory

    def get_game_state(
        self, project_id: str, instance_id: str = "default"
    ) -> WorldState:
        """按实例取运行时世界状态；无缓存时从项目资产构建"""
        key = (project_id, instance_id)
        state = self.game_states.get(key)
        if state is None:
            project = self._get_or_load_project(project_id)
            state = WorldState.from_project(project)
            self.game_states[key] = state
        return state

    def _narrator_llm(self):
        """游戏内叙述 / 开场使用的低延迟模型（narrator 角色）"""
        if self.router is None:
            return None
        try:
            llm, _ = self.router.get_llm_for_role("narrator")
            return llm
        except Exception:
            return None

    def _game_prose_fn(self, prompt: str, state: WorldState) -> str:
        """游戏模式叙述润色：把裁决事实改写成叙事。

        使用 narrator 角色（默认快速模型）控制单回合延迟；
        任何失败（无可用模型 / 网络异常）都返回空串，由渲染层回退到确定性文本，
        保证游戏不会因为 LLM 不可用而中断。
        """
        llm = self._narrator_llm()
        if llm is None:
            return ""
        try:
            return str(llm.call([{"role": "user", "content": prompt}])).strip()
        except Exception:
            return ""

    def _memory_llm(self):
        """记忆压缩使用的低温模型，避免压缩时脑补。"""
        if self.router is None:
            return None
        try:
            llm, _ = self.router.get_llm_for_role("memory")
            return llm
        except Exception:
            return None

    def _memory_compress_fn(self, prompt: str) -> str:
        """分层记忆压缩：让 LLM 按目标层规则动态压缩。

        失败或没有可用模型时返回空串，由 LayeredMemory 走确定性选择性兜底。
        """
        llm = self._memory_llm()
        if llm is None:
            return ""
        try:
            return str(llm.call([{"role": "user", "content": prompt}])).strip()
        except Exception:
            return ""

    def _opening_prompt(self, project: NovelProject, state: WorldState) -> str:
        """构造开场叙述提示：只喂公开设定与首章大纲，不暴露秘密。"""
        player_loc = state.location_of("玩家") or next(
            iter(state.locations), ""
        )
        present = [
            name
            for name in state.characters_at(player_loc)
            if name != "玩家"
        ]
        lines = [
            "请为下面这部互动小说写一段开场（前情提要）。",
            "要求：",
            "- 第二人称「你」，150-250 字，克制、有画面感；",
            "- 交代你是谁、身在何处、眼下最紧迫的处境；",
            "- 至少写到两位在场角色的态度或动作线索；",
            "- 只写已经存在的世界状态，不要替玩家做决定，不要写玩家尚未采取的行动；",
            "- 不要解释系统、规则或身份设定。",
            "",
            f"作品：{project.title}",
        ]
        if project.style:
            lines.append(f"文风：{project.style}")
        if project.description:
            lines.append(f"设定：{project.description}")
        lines.append(f"开场地点：{player_loc}")
        if present:
            lines.append("在场角色：")
            for name in present:
                char = project.get_character(name)
                if char is None:
                    lines.append(f"- {name}")
                    continue
                detail = f"- {name}：{char.persona}"
                if char.motivation:
                    detail += f"；动机：{char.motivation}"
                lines.append(detail)
        chapters = get_repository().list_chapters(project.project_id)
        if chapters and chapters[0].get("outline"):
            lines.append(
                f"首章大纲（只作背景，不要照抄）：{chapters[0]['outline']}"
            )
        return "\n".join(lines)

    @staticmethod
    def _opening_fallback(project: NovelProject, state: WorldState) -> str:
        """LLM 不可用时的确定性开场，保证玩家始终有前情提要。"""
        player_loc = state.location_of("玩家") or next(
            iter(state.locations), "无名之地"
        )
        present = [
            name
            for name in state.characters_at(player_loc)
            if name != "玩家"
        ]
        lines = []
        if project.description.strip():
            lines.append(project.description.strip())
        scene_line = f"此刻你身在{player_loc}。"
        if present:
            scene_line += "在场的有：" + "、".join(present) + "。"
        lines.append(scene_line)
        chapters = get_repository().list_chapters(project.project_id)
        if chapters and chapters[0].get("outline"):
            lines.append(f"眼下：{chapters[0]['outline'].strip()}")
        return "\n\n".join(lines)

    async def generate_opening(
        self, project_id: str, instance_id: str = "default"
    ) -> dict:
        """生成进入游戏模式时的开场叙述，不推进世界状态。"""
        project = self._get_or_load_project(project_id)
        state = self.get_game_state(project_id, instance_id)

        text = ""
        llm = self._narrator_llm()
        if llm is not None:
            try:
                raw = await asyncio.to_thread(
                    llm.call,
                    [
                        {
                            "role": "user",
                            "content": self._opening_prompt(project, state),
                        }
                    ],
                )
                text = str(raw).strip()
            except Exception:
                text = ""
        if not text:
            text = self._opening_fallback(project, state)

        scene = SceneRenderer().render(
            state,
            state,
            AdjudicationResult(
                success=True, outcome="idle", narrative=text
            ),
            actor="玩家",
        )
        return {
            "text": scene.text,
            "choices": scene.choices,
            "scene": scene.model_dump(mode="json"),
        }

    async def play_turn(
        self, project_id: str, boot: TurnBoot
    ) -> TurnResult:
        """执行一个双模式回合（可选集成 SceneCrew 多 Agent 叙事链）"""
        project = self._get_or_load_project(project_id)
        if boot.world_state is None:
            boot = boot.model_copy(
                update={
                    "world_state": self.get_game_state(
                        project_id, boot.instance_id
                    )
                }
            )
        boot = boot.model_copy(update={"project_id": project_id})
        if boot.provider_api_keys:
            # 只在运行时内存注册，供后续 LLM 调用使用
            self.registry.apply_provider_keys(boot.provider_api_keys)

        memory = self.memory_for(project_id, backend=boot.memory_backend)
        crew = self._crew_for(project_id)
        rag = self.rags.get(project_id)
        loop = TurnLoop(
            project,
            instance_id=boot.instance_id,
            memory=memory,
            extensions=self.extension_registry,
            save_service=self.save_service,
            renderer=SceneRenderer(prose_fn=self._game_prose_fn),
            crew=crew,
            rag=rag,
        )
        result = await loop.run(boot)
        key = (project_id, boot.instance_id)
        self.game_states[key] = result.state
        self.last_turns[key] = result
        return result

    def switch_game_mode(
        self, project_id: str, target_mode: str, instance_id: str = "default"
    ) -> tuple[WorldState, str]:
        """模式切换：先落 checkpoint，再更新模式"""
        state = self.get_game_state(project_id, instance_id)
        controller = AuthorityController()

        def checkpoint(world: WorldState, label: str) -> str:
            record = self.save_service.save(
                project_id, world, StageScene(), label=label, kind="checkpoint"
            )
            return record.save_id

        new_state, checkpoint_id = controller.switch_mode(
            state, target_mode, checkpoint_fn=checkpoint
        )
        self.game_states[(project_id, instance_id)] = new_state
        return new_state, checkpoint_id

    def create_save(
        self,
        project_id: str,
        instance_id: str = "default",
        label: str = "",
        backlog: list[dict] | None = None,
    ):
        state = self.get_game_state(project_id, instance_id)
        last = self.last_turns.get((project_id, instance_id))
        scene = last.scene if last is not None else StageScene()
        memory = self.game_memories.get(project_id)
        return self.save_service.save(
            project_id,
            state,
            scene,
            label=label,
            memory_snapshot=memory.snapshot() if memory else {},
            metadata={"backlog": list(backlog or [])},
            kind="story",
        )

    def list_saves(self, project_id: str):
        return self.save_service.list(project_id)

    def load_save(
        self, project_id: str, save_id: str, instance_id: str = "default"
    ):
        record = self.save_service.load(project_id, save_id)
        state = state_from_save(record)
        self.game_states[(project_id, instance_id)] = state
        if record.memory_snapshot:
            self.game_memories[project_id] = LayeredMemory.restore(
                project_id,
                record.memory_snapshot,
                repo=get_repository(),
                settings=self._memory_settings_for(project_id),
                compress_fn=self._memory_compress_fn,
            )
        # 同步「最近一回合」，保证读档后立即存档能保存读档时点的场景与选项
        scene = StageScene(
            directives=[
                StageDirective.model_validate(d) for d in record.directives
            ],
            text=record.text,
            choices=[dict(c) for c in record.choices],
        )
        self.last_turns[(project_id, instance_id)] = TurnResult(
            turn_id=f"loaded_{record.save_id}",
            trace_id="",
            project_id=project_id,
            instance_id=instance_id,
            state=state,
            state_delta=StateDelta(),
            scene=scene,
            text=record.text,
            choices=[dict(c) for c in record.choices],
        )
        return record

    def memory_overview(self, project_id: str) -> dict:
        memory = self.memory_for(project_id)
        items = [
            item.model_dump(mode="json")
            for item in memory.items.values()
        ]
        return {
            "project_id": project_id,
            "backend": memory.backend_name,
            "counts": memory.counts(),
            "settings": memory.settings.to_dict(),
            "tiers": [spec.model_dump(mode="json") for spec in memory.settings.tiers],
            "canon": {
                "max_items": memory.settings.canon_max_items,
                "compress_into": memory.settings.canon_compress_into,
                "compress_max_chars": memory.settings.canon_compress_max_chars,
            },
            "demotion": {
                tier: memory.settings.rule_for(tier).model_dump(mode="json")
                for tier in ("long_term", "canon")
            },
            "reheat_hits": memory.settings.reheat_hits,
            "items": items,
            "prompt_block": memory.prompt_block(),
        }

    def set_memory_backend(self, project_id: str, backend: str) -> dict:
        if backend not in ("fts", "vector", "hybrid"):
            raise ValueError(f"不支持的检索后端: {backend}")
        return self.update_memory_config(
            project_id, {"retrieval": {"backend": backend}}
        )

    def update_memory_config(self, project_id: str, patch: dict) -> dict:
        """按项目局部更新记忆配置（构建校验通过后整体落库）"""
        repo = get_repository()
        merged = _deep_merge(repo.load_memory_config(project_id), patch)
        settings = MemorySettings.from_dict(merged)
        repo.save_memory_config(project_id, settings.to_dict())
        self.game_memories.pop(project_id, None)
        return self.memory_overview(project_id)

    def resolve_extensions(
        self, instance_id: str, enabled: list[str] | None = None
    ) -> dict:
        host = self.extension_registry.for_instance(
            instance_id, enabled=enabled
        )
        return host.resolve()


# 全局引擎实例
engine = NovelEngine()
