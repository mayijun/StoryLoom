"""
CrewAI引擎桥接：连接FastAPI和已有的CrewAI多Agent后端
"""

import os
import sys
import json
import asyncio
from typing import List, AsyncGenerator
from pathlib import Path

# 将已有的CrewAI后端加入路径
BACKEND_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from llm.providers import ModelRegistry
from llm.router import AgentModelRouter
from agents.factory import AgentFactory
from assets.models import CharacterAsset, LocationAsset, NovelProject, Foreshadowing
from memory.manager import CoreMemory, SimpleRAGMemory
from flow.scene_flow import SceneGenerationFlow
from api.schemas import (
    GenerateSceneRequest, GenerationStepUpdate,
    GenerateSceneResponse, ForeshadowingView,
)


class NovelEngine:
    """
    小说引擎：封装CrewAI后端，提供API友好的接口
    支持多项目管理和SSE实时推送
    """

    def __init__(self):
        self.registry = ModelRegistry(
            str(BACKEND_ROOT / "config" / "model_config.yaml")
        )
        self.router = AgentModelRouter(self.registry)
        self.factory = AgentFactory(self.router)

        # 项目存储（生产环境用数据库）
        self.projects: dict[str, NovelProject] = {}
        self.memories: dict[str, CoreMemory] = {}
        self.rags: dict[str, SimpleRAGMemory] = {}

    def get_available_models(self) -> List[str]:
        return self.registry.list_available()

    def create_project(self, project_id, title, style) -> NovelProject:
        project = NovelProject(
            project_id=project_id,
            title=title,
            style=style,
            characters=[],
            locations=[],
        )
        self.projects[project_id] = project
        self.memories[project_id] = CoreMemory()
        self.rags[project_id] = SimpleRAGMemory(project_id)
        return project

    def get_project(self, project_id) -> NovelProject:
        return self.projects.get(project_id)

    def add_character(self, project_id, char: CharacterAsset):
        project = self.projects[project_id]
        project.characters.append(char)
        # 自动加入RAG
        self.rags[project_id].add(
            f"char_{char.name}",
            f"{char.name}: {char.persona}. 动机: {char.motivation}",
            {"type": "character"},
        )

    def add_location(self, project_id, loc: LocationAsset):
        project = self.projects[project_id]
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
        project = self.projects[request.project_id]
        memory = self.memories[request.project_id]
        rag = self.rags[request.project_id]

        # 更新在场角色
        memory.characters_present = request.present_character_names

        flow = SceneGenerationFlow(
            project=project,
            memory=memory,
            rag=rag,
            factory=self.factory,
            scene_brief=request.scene_brief,
            present_characters=request.present_character_names,
        )
        flow.render_mode = request.render_mode

        # 在线程池中执行（CrewAI kickoff 是同步的）
        loop = asyncio.get_event_loop()
        final_text = await loop.run_in_executor(None, flow.kickoff)

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
            for i, (aid, mkey) in enumerate(self.factory._created_agents)
        ]

        return GenerateSceneResponse(
            scene_id=f"scene_{project.scene_count}",
            final_prose=str(final_text),
            steps=steps,
            foreshadowing_updates=fs_views,
        )


# 全局引擎实例
engine = NovelEngine()
