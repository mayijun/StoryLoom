"""
最小化 Demo —— 仅需 DeepSeek API Key 即可运行

相比 main.py，这里只保留一个主角 + 一个群演角色，
用最短的 prompt 跑通完整流程，用于验证环境是否配置正确。

运行：
    python examples/minimal_demo.py
"""

import sys
from pathlib import Path

# 允许直接运行 `python examples/minimal_demo.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from storyloom.crews.scene_crew.crew import SceneCrew
from storyloom.models import CharacterAsset, LocationAsset, NovelProject
from storyloom.flows.scene_flow import SceneGenerationFlow
from storyloom.llm.providers import ModelRegistry
from storyloom.llm.router import AgentModelRouter
from storyloom.memory import CoreMemory, SimpleRAGMemory


def main():
    load_dotenv()

    registry = ModelRegistry()
    router = AgentModelRouter(registry)
    crew = SceneCrew(router)

    project = NovelProject(
        project_id="demo_minimal",
        title="雾中旅人",
        style="克制、悬疑、第三人称有限视角",
        characters=[
            CharacterAsset(
                name="林夏",
                importance_tier="primary",
                persona="冷静、善于隐藏情绪",
                motivation="寻找失踪的姐姐",
            ),
            CharacterAsset(
                name="旅店老板",
                importance_tier="background",
                persona="沉默寡言",
                motivation="只想息事宁人",
            ),
        ],
        locations=[
            LocationAsset(
                name="雾港旅店",
                description="潮湿昏暗的小旅店大堂",
            )
        ],
    )

    memory = CoreMemory(
        current_location="雾港旅店",
        characters_present=["林夏", "旅店老板"],
        recent_scene_summaries=["林夏刚抵达雾港，投宿在这家旅店。"],
    )

    rag = SimpleRAGMemory(project.project_id)
    rag.add(
        "lore_1",
        "雾港常年被海雾笼罩，镇上的人都隐瞒着秘密。",
        {"type": "lore"},
    )

    flow = SceneGenerationFlow(
        project=project,
        memory=memory,
        rag=rag,
        crew=crew,
        scene_brief="林夏向旅店老板打听姐姐的消息，老板欲言又止。",
        present_characters=["林夏", "旅店老板"],
    )

    print("🎬 最小化 Demo 开始生成场景...\n")
    print(flow.kickoff())


if __name__ == "__main__":
    main()
