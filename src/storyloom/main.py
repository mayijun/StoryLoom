"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

织章 StoryLoom —— CLI 演示入口（多模型）

⚠️  说明：默认入口为 `python app.py`（Web 模式）。
本文件用于命令行直接演示小说生成流程，便于快速调试后端逻辑。

流程：意外提案 → 伏笔建议 → 导演裁决 → 角色互动
     → 一致性检测 → 润色 → 记忆与伏笔更新
"""

from dotenv import load_dotenv

from storyloom.crews.scene_crew.crew import SceneCrew
from storyloom.models import (
    CharacterAsset,
    Foreshadowing,
    LocationAsset,
    NovelProject,
)
from storyloom.flows.scene_flow import SceneGenerationFlow
from storyloom.llm.providers import ModelRegistry
from storyloom.llm.router import AgentModelRouter
from storyloom.memory import CoreMemory, SimpleRAGMemory


def build_project() -> NovelProject:
    """定义演示项目资产（含预埋伏笔）"""
    return NovelProject(
        project_id="demo_v2_surprise",
        title="雾中旅人",
        style="克制、悬疑、第三人称有限视角",
        surprise_cooldown=3,       # 每 3 个场景最多 1 次重大意外
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
                description="旅店墙上挂着一幅旧航海图，"
                            "上面有几个被涂改过的港口名称",
                planted_in_scene="scene_0",
                target_revelation="涂改的港口正是林夏姐姐的逃亡路线",
                linked_characters=["林夏", "旅店老板"],
                max_dormant_scenes=4,
            ),
            Foreshadowing(
                foreshadow_id="fs_sisters_token",
                description="林夏姐姐留下的信物不翼而飞",
                planted_in_scene="scene_0",
                target_revelation="信物被旅店老板收走保管",
                linked_characters=["林夏", "旅店老板"],
                max_dormant_scenes=3,
            ),
        ],
    )


def build_memory(project: NovelProject):
    """初始化核心记忆 + RAG 记忆"""
    memory = CoreMemory(
        current_location="雾港旅店",
        characters_present=["林夏", "阿泽", "旅店老板"],
        recent_scene_summaries=[
            "林夏刚抵达雾港，发现姐姐留下的信物不翼而飞。"
        ],
    )

    rag = SimpleRAGMemory(project.project_id)
    rag.add(
        "lore_1",
        "雾港常年被海雾笼罩，传闻镇上的人都在隐瞒秘密。",
        {"type": "lore"},
    )
    rag.add(
        "lore_2",
        "旅店墙上挂着一幅旧航海图，标注了几个被涂改过的港口名。",
        {"type": "location_detail"},
    )
    rag.add(
        "lore_3",
        "阿泽在雾港有一个秘密的情报网，他表面是小混混，"
        "实际上为多方势力传递消息。",
        {"type": "character_secret"},
    )
    return memory, rag


def run_demo():
    load_dotenv()

    # 1. 初始化模型路由器
    registry = ModelRegistry()
    router = AgentModelRouter(registry)
    router.print_assignment_table()
    print(f"🔌 当前可用模型: {registry.list_available()}\n")

    # 2. 初始化场景 Crew
    crew = SceneCrew(router)

    # 3. 项目资产与记忆
    project = build_project()
    memory, rag = build_memory(project)

    # 4. 展示初始伏笔状态
    print("📌 初始伏笔状态：")
    for f in project.foreshadowings:
        print(
            f"  [{f.foreshadow_id}] {f.description} "
            f"→ {f.target_revelation}"
        )
    print()

    # 5. 启动场景生成
    print("🎬 场景生成 v2：集成意外 Agent + 伏笔 Agent\n")

    flow = SceneGenerationFlow(
        project=project,
        memory=memory,
        rag=rag,
        crew=crew,
        scene_brief=(
            "林夏在旅店大堂被阿泽搭讪，试探她是否知道姐姐下落。"
            "旅店老板在柜台后面擦杯子，偶尔抬头看一眼。"
        ),
        present_characters=["林夏", "阿泽", "旅店老板"],
    )

    final_text = flow.kickoff()

    # 6. 输出结果
    print("\n" + "=" * 60)
    print("📖 最终正文")
    print("=" * 60)
    print(final_text)

    print("\n" + "=" * 60)
    print("📌 更新后的伏笔状态")
    print("=" * 60)
    for f in project.foreshadowings:
        emoji = {
            "planted": "🌱",
            "reinforced": "💪",
            "activated": "🎯",
            "resolved": "✅",
            "subverted": "🔄",
            "abandoned": "⚠️",
        }.get(f.status.value, "❓")
        print(
            f"  {emoji} [{f.foreshadow_id}] {f.description}\n"
            f"     状态: {f.status.value} | "
            f"强化{f.reinforcement_count}次 | "
            f"距上次提及{f.scenes_since_last_mention}场景"
        )

    crew.print_creation_summary()


if __name__ == "__main__":
    run_demo()
