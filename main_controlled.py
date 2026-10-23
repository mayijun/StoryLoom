"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

⚠️  实验性模块（Experimental / Optional）
------------------------------------------
本文件是「系统控制论增强版」的 CLI 测试入口，仍处于实验阶段，
**非必要时不加载**。默认入口请使用 `python app.py` 启动 Web 模式。

在基础版流程上叠加 7 大控制论原理：
反馈闭环、统计滤波、端到端评估、灵敏度分析、
解耦控制、分层管控、人机结合。
"""

from dotenv import load_dotenv

from agents.factory import AgentFactory
from assets.models import (
    CharacterAsset,
    Foreshadowing,
    LocationAsset,
    NovelProject,
)
from control.hierarchy import SystemOrchestrator
from control.robustness import (
    DecouplingValidator,
    SensitivityAnalyzer,
)
from flow.controlled_scene_flow import ControlledSceneFlow
from llm.providers import ModelRegistry
from llm.router import AgentModelRouter
from memory.manager import CoreMemory, SimpleRAGMemory


def build_project() -> NovelProject:
    return NovelProject(
        project_id="demo_v3_controlled",
        title="雾中旅人",
        style="克制、悬疑、第三人称有限视角",
        surprise_cooldown=3,
        characters=[
            CharacterAsset(
                name="林夏",
                importance_tier="primary",
                persona="冷静、善于隐藏情绪，习惯用反问句",
                motivation="寻找失踪的姐姐",
                secrets="她其实知道姐姐去向，但故意装作不知情",
            ),
            CharacterAsset(
                name="阿泽",
                importance_tier="secondary",
                persona="话多、爱打探消息",
                motivation="想从林夏这里套出情报换钱",
            ),
            CharacterAsset(
                name="旅店老板",
                importance_tier="background",
                persona="沉默寡言，偶尔目光犀利",
                motivation="只想息事宁人，但似乎知道些什么",
            ),
        ],
        locations=[
            LocationAsset(
                name="雾港旅店",
                description="潮湿、灯光昏暗的小旅店大堂",
            )
        ],
        foreshadowings=[
            Foreshadowing(
                foreshadow_id="fs_nautical_map",
                description="旅店墙上被涂改的旧航海图",
                planted_in_scene="scene_0",
                target_revelation="涂改港口是姐姐的逃亡路线",
                linked_characters=["林夏", "旅店老板"],
                max_dormant_scenes=4,
            ),
        ],
    )


def run_demo():
    load_dotenv()

    # 1. 初始化
    registry = ModelRegistry("config/model_config.yaml")
    router = AgentModelRouter(registry)
    factory = AgentFactory(router)
    orchestrator = SystemOrchestrator(auto_mode=True)

    # 打印系统分析
    router.print_assignment_table()
    SensitivityAnalyzer.print_sensitivity_map()
    DecouplingValidator.print_dependency_graph()

    # 2. 项目资产
    project = build_project()

    # 3. 记忆
    memory = CoreMemory(
        current_location="雾港旅店",
        characters_present=["林夏", "阿泽", "旅店老板"],
        recent_scene_summaries=[
            "林夏刚抵达雾港，姐姐的信物不翼而飞。"
        ],
    )

    rag = SimpleRAGMemory(project.project_id)
    rag.add(
        "lore_1",
        "雾港常年海雾笼罩，人人隐瞒秘密。",
        {"type": "lore"},
    )

    # 4. 启动
    print("\n🎬 v3: 系统控制论增强版\n")

    flow = ControlledSceneFlow(
        project=project,
        memory=memory,
        rag=rag,
        factory=factory,
        orchestrator=orchestrator,
        scene_brief="林夏在旅店大堂被阿泽搭讪，试探来意",
        present_characters=["林夏", "阿泽", "旅店老板"],
    )

    final_text = flow.kickoff()

    print("\n" + "=" * 60)
    print("📖 最终正文（系统控制论增强版）")
    print("=" * 60)
    print(final_text)

    factory.print_creation_summary()


if __name__ == "__main__":
    run_demo()
