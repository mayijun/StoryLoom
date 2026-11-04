"""
CrewAI引擎桥接：连接FastAPI和已有的CrewAI多Agent后端
"""

import json
import asyncio
from typing import List
from pathlib import Path

from dotenv import load_dotenv

# 必须在创建 ModelRegistry/Router 之前加载根目录 .env
# （router.is_available 依赖环境变量中的 API Key）
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from storyloom.llm.providers import ModelRegistry
from storyloom.llm.router import AgentModelRouter
from storyloom.crews.scene_crew.crew import SceneCrew
from storyloom.db import DEFAULT_PROJECT_ID, get_repository
from storyloom.models import CharacterAsset, LocationAsset, NovelProject, Foreshadowing
from storyloom.memory import CoreMemory, SimpleRAGMemory
from storyloom.flows.scene_flow import SceneGenerationFlow
from storyloom.api.schemas import (
    GenerateSceneRequest, GenerationStepUpdate,
    GenerateSceneResponse, ForeshadowingView,
)


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

    # ---------------- 项目管理 ----------------

    def _build_project(self, meta: dict) -> NovelProject:
        """从 projects 表的元数据构造 NovelProject 运行时对象"""
        project = NovelProject(
            project_id=meta["project_id"],
            title=meta["title"],
            style=meta["style"],
            characters=[],
            locations=[],
        )
        project.scene_count = meta["scene_count"]
        project.foreshadowings = []  # 伏笔暂不落库，保持与现有流程一致
        # characters / locations 当前也不落库，置空即可
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

    def add_character(self, project_id, char: CharacterAsset):
        project = self._get_or_load_project(project_id)
        project.characters.append(char)
        # 同步更新 DB 中的 character_count
        get_repository().update_project_stats(
            project_id, character_count=len(project.characters)
        )
        # 自动加入RAG
        self.rags[project_id].add(
            f"char_{char.name}",
            f"{char.name}: {char.persona}. 动机: {char.motivation}",
            {"type": "character"},
        )

    def add_location(self, project_id, loc: LocationAsset):
        project = self._get_or_load_project(project_id)
        project.locations.append(loc)
        self.rags[project_id].add(
            f"loc_{loc.name}",
            f"{loc.name}: {loc.description}",
            {"type": "location"},
        )

    async def generate_scene(
        self, request: GenerateSceneRequest
    ) -> GenerateSceneResponse:
        """生成场景（同步执行，异步包装）"""
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
        )
        flow.render_mode = request.render_mode

        # 在线程池中执行（CrewAI kickoff 是同步的）
        loop = asyncio.get_event_loop()
        final_text = await loop.run_in_executor(None, flow.kickoff)

        # scene_flow 在 kickoff 内部已经 project.scene_count += 1；
        # 把更新后的统计写回数据库，保证下次重启仍能看到最新值
        get_repository().update_project_stats(
            request.project_id,
            scene_count=project.scene_count,
            character_count=len(project.characters),
            foreshadowing_count=len(project.foreshadowings),
        )

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
            scene_id=f"scene_{project.scene_count}",
            final_prose=str(final_text),
            steps=steps,
            foreshadowing_updates=fs_views,
        )


# 全局引擎实例
engine = NovelEngine()
