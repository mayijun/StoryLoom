"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

Flow 编排核心 v2：集成 SurpriseAgent + ForeshadowingAgent

新增 pre-scene planning 阶段（意外+伏笔提案 → 导演决策）
每个步骤内部的 Agent 自动通过 SceneCrew 获得最适合的 AI 模型。

参考：
- StoryWriter（清华 KEG）: 多 Agent 分工评估体系
- Showrunner Agents: 戏剧算子注入机制
- CreAgentive: 知识图谱伏笔约束
"""

import json
from typing import List, Literal, Optional

from crewai import Crew, Process, Task
from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel, Field

from storyloom.crews.scene_crew.crew import SceneCrew
from storyloom.models import (
    Foreshadowing,
    ForeshadowStatus,
    NovelProject,
)
from storyloom.memory import CoreMemory, SimpleRAGMemory


class ConsistencyReport(BaseModel):
    """一致性检测 Agent 的结构化输出"""

    passed: bool
    conflicts: List[str] = Field(default_factory=list)
    severity: Literal["none", "minor", "major"] = "none"


def parse_json_block(raw: str) -> dict:
    """从模型输出中截取并解析 JSON（推理模型常夹带说明文字）"""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(raw[start: end + 1])


def apply_foreshadow_ops(project: NovelProject, ops: List[dict]):
    """
    把导演采纳的伏笔操作应用到项目状态

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
                target_revelation=new_data.get(
                    "target_revelation", ""
                ),
                linked_characters=new_data.get(
                    "linked_characters", []
                ),
                max_dormant_scenes=new_data.get(
                    "max_dormant_scenes", 5
                ),
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


def advance_scene_counters(project: NovelProject):
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


class SceneFlowState(BaseModel):
    project: Optional[NovelProject] = None
    memory: Optional[CoreMemory] = None
    scene_brief: Optional[str] = None
    surprise_proposal: Optional[str] = None
    foreshadowing_ops: Optional[str] = None
    director_intent: Optional[str] = None
    actor_log: Optional[str] = None
    consistency_report: Optional[ConsistencyReport] = None
    final_prose: Optional[str] = None
    retry_count: int = 0


class SceneGenerationFlow(Flow[SceneFlowState]):
    """
    场景生成 Flow v2

    流程：
    0a. SurpriseAgent 提出意外事件提案
    0b. ForeshadowingAgent 提出伏笔操作建议
    1.  DirectorAgent 综合两者 + 场景需求，产出场景意图包
    2.  RAG 检索背景资料
    3.  动态组建 Crew 进行角色互动
    4.  一致性检测（冲突可回退重试）
    5.  润色成正式小说正文
    6.  写回记忆 + 更新伏笔状态
    """

    def __init__(
        self,
        project: NovelProject,
        memory: CoreMemory,
        rag: SimpleRAGMemory,
        crew: SceneCrew,
        scene_brief: str,
        present_characters: List[str],
        max_retries: int = 1,
    ):
        super().__init__()
        self.state.project = project
        self.state.memory = memory
        self.state.scene_brief = scene_brief
        self.rag = rag
        self.crew = crew
        self.present_characters = present_characters
        self.max_retries = max_retries
        self.rag_context = ""

    # ============================================================
    # Step 0a: SurpriseAgent 提出意外事件提案
    # ============================================================
    @start()
    def propose_surprise(self):
        """
        意外 Agent 评估当前场景是否需要意外元素

        频率控制：如果距上次重大意外的场景数 < cooldown，
        则在 prompt 中明确告知"本场景不建议重大意外"。
        """
        project = self.state.project
        scenes_since_last = (
            project.scene_count - project.last_major_surprise_scene
        )
        cooldown_hint = ""
        if scenes_since_last < project.surprise_cooldown:
            cooldown_hint = (
                f"\n⚠️ 距上次重大意外仅过了{scenes_since_last}个场景"
                f"（冷却期{project.surprise_cooldown}），"
                f"本场景强烈建议不要有重大意外，"
                f"可以有 minor 级别的小意外。"
            )

        active_foreshadowings = [
            f"- [{f.foreshadow_id}] {f.description} "
            f"(状态: {f.status.value}, "
            f"已{f.scenes_since_last_mention}场景未提及)"
            for f in project.foreshadowings
            if f.status
            in (ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED)
        ]
        foreshadow_context = (
            "\n".join(active_foreshadowings)
            if active_foreshadowings
            else "（当前无活跃伏笔）"
        )

        surprise_agent = self.crew.surprise()
        task = Task(
            description=(
                f"故事: {project.title}\n"
                f"{self.state.memory.as_prompt_block()}\n"
                f"本场景要求: {self.state.scene_brief}\n"
                f"{cooldown_hint}\n\n"
                f"当前活跃伏笔（可尝试关联）:\n"
                f"{foreshadow_context}\n\n"
                "请评估本场景是否需要意外元素。\n"
                "如果需要，输出 JSON 提案，字段:\n"
                "- surprise_type: character/information/environment/"
                "relationship/temporal\n"
                "- description: 意外事件描述\n"
                "- justification: 为什么合理\n"
                "- impact_on_plot: 对后续剧情影响\n"
                "- linked_foreshadow_id: 可关联的伏笔 ID(可为 null)\n"
                "- severity: minor/moderate/major\n\n"
                '如果不需要，输出: {"no_surprise": true, '
                '"reason": "原因说明"}'
            ),
            expected_output="JSON 意外事件提案或不需要意外的声明",
            agent=surprise_agent,
        )
        crew = Crew(
            agents=[surprise_agent],
            tasks=[task],
            process=Process.sequential,
        )
        result = str(crew.kickoff())
        self.state.surprise_proposal = result
        return result

    # ============================================================
    # Step 0b: ForeshadowingAgent 提出伏笔操作建议
    # ============================================================
    @listen(propose_surprise)
    def propose_foreshadowing_ops(self, surprise_proposal: str):
        """
        伏笔 Agent 检查所有伏笔状态，提出本场景的操作建议

        关键逻辑：
        - 检查哪些伏笔即将"超时"
        - 检查是否有伏笔可以在本场景回收
        - 检查 SurpriseAgent 的提案是否可以与伏笔联动
        """
        project = self.state.project

        foreshadow_table = []
        urgent_alerts = []
        for f in project.foreshadowings:
            if f.status in (
                ForeshadowStatus.PLANTED,
                ForeshadowStatus.REINFORCED,
            ):
                foreshadow_table.append(
                    f"- [{f.foreshadow_id}] {f.description}\n"
                    f"  状态: {f.status.value} | "
                    f"已强化{f.reinforcement_count}次 | "
                    f"距上次提及{f.scenes_since_last_mention}场景 | "
                    f"容忍上限{f.max_dormant_scenes}场景\n"
                    f"  预期揭示: {f.target_revelation}\n"
                    f"  关联角色: {', '.join(f.linked_characters)}"
                )
                if (
                    f.scenes_since_last_mention
                    >= f.max_dormant_scenes - 1
                ):
                    urgent_alerts.append(
                        f"🚨 [{f.foreshadow_id}] {f.description} "
                        f"即将超时！必须在本场景提及或处理"
                    )

        foreshadow_status = (
            "\n".join(foreshadow_table)
            if foreshadow_table
            else "（当前无活跃伏笔）"
        )
        alerts = (
            "\n".join(urgent_alerts)
            if urgent_alerts
            else "（无紧急提醒）"
        )

        foreshadowing_agent = (
            self.crew.foreshadowing()
        )
        task = Task(
            description=(
                f"故事: {project.title}\n"
                f"{self.state.memory.as_prompt_block()}\n"
                f"本场景: {self.state.scene_brief}\n"
                f"在场角色: {', '.join(self.present_characters)}\n\n"
                f"===== 当前伏笔状态表 =====\n{foreshadow_status}\n\n"
                f"===== 紧急提醒 =====\n{alerts}\n\n"
                f"===== SurpriseAgent 的意外提案 =====\n"
                f"{surprise_proposal}\n\n"
                "请输出 JSON 格式的伏笔操作建议列表，每项包含:\n"
                "- action: plant/reinforce/activate/resolve/subvert/alert\n"
                "- foreshadow_id: 操作的伏笔 ID(新建时为 null)\n"
                "- description: 具体操作描述\n"
                "- new_foreshadow: 若 action=plant，填写新伏笔详情\n"
                "  (description, target_revelation, "
                "linked_characters, max_dormant_scenes)\n"
                "- link_to_surprise: 是否与意外提案联动(bool)\n\n"
                '输出格式: {"operations": [...]}'
            ),
            expected_output="JSON 伏笔操作建议列表",
            agent=foreshadowing_agent,
        )
        crew = Crew(
            agents=[foreshadowing_agent],
            tasks=[task],
            process=Process.sequential,
        )
        result = str(crew.kickoff())
        self.state.foreshadowing_ops = result
        return result

    # ============================================================
    # Step 1: 导演综合意外+伏笔提案，产出最终场景意图包
    # ============================================================
    @listen(propose_foreshadowing_ops)
    def plan_scene(self, foreshadowing_ops: str):
        """
        导演 Agent 现在有三个输入来源：
        1. 用户的场景要求
        2. SurpriseAgent 的意外提案
        3. ForeshadowingAgent 的伏笔操作建议

        导演做最终裁决：采纳 / 修改 / 否决各提案
        """
        director = self.crew.director()
        task = Task(
            description=(
                f"故事: {self.state.project.title}\n"
                f"{self.state.memory.as_prompt_block()}\n"
                f"用户场景要求: {self.state.scene_brief}\n\n"
                f"===== 意外 Agent 提案 =====\n"
                f"{self.state.surprise_proposal}\n\n"
                f"===== 伏笔 Agent 建议 =====\n"
                f"{foreshadowing_ops}\n\n"
                "作为导演，请综合以上所有信息，输出最终的"
                "'场景意图包' JSON:\n"
                "- goal: 戏剧目标\n"
                "- conflict: 冲突/伏笔\n"
                "- emotion_arc: 情绪曲线\n"
                "- forbidden: 禁止发生的事\n"
                "- adopted_surprise: 采纳的意外（null 表示不采纳）\n"
                "- adopted_foreshadow_ops: 采纳的伏笔操作列表\n"
                "- rejection_reasons: 否决某提案的理由（如有）\n\n"
                "你有权否决任何提案，但必须给出理由。"
            ),
            expected_output="JSON 场景意图包",
            agent=director,
        )
        crew = Crew(
            agents=[director],
            tasks=[task],
            process=Process.sequential,
        )
        result = crew.kickoff()
        self.state.director_intent = str(result)
        return self.state.director_intent

    # ============================================================
    # Step 2: RAG 检索背景资料
    # ============================================================
    @listen(plan_scene)
    def gather_rag_context(self, director_intent: str):
        """按需检索背景设定，不是每次都硬塞全部设定"""
        query = self.state.scene_brief + " " + director_intent
        docs = self.rag.query(query, n_results=3)
        self.rag_context = "\n".join(docs) if docs else "（无额外背景）"
        return self.rag_context

    # ============================================================
    # Step 3: 角色互动（动态组建 Crew）
    # ============================================================
    @listen(gather_rag_context)
    def run_actor_interaction(self, rag_context: str):
        """
        核心步骤：根据出场角色动态组建 Crew
        - primary 角色 → 每个独立一个 ProtagonistAgent
        - secondary/background 角色 → 合并到 EnsembleAgent
        """
        project = self.state.project
        present = self.present_characters

        primary_chars = [
            c for c in project.characters
            if c.name in present and c.importance_tier == "primary"
        ]
        secondary_chars = [
            c for c in project.characters
            if c.name in present and c.importance_tier != "primary"
        ]

        agents = []
        tasks = []

        # 每个重要角色独立一个 Agent
        for char in primary_chars:
            agent = self.crew.protagonist(char)
            agents.append(agent)
            tasks.append(Task(
                description=(
                    f"导演意图(仅供参考，不要直接复述):\n"
                    f"{self.state.director_intent}\n\n"
                    f"背景资料:\n{rag_context}\n\n"
                    f"{self.state.memory.as_prompt_block()}\n\n"
                    f"请以【{char.name}】的身份，给出这一刻的"
                    f"内心想法、台词和行动。\n"
                    f"简洁、符合人设，只写行动日志式的描述。"
                ),
                expected_output=f"{char.name}的行动与台词记录",
                agent=agent,
            ))

        # 所有次要角色合并给一个群演 Agent
        if secondary_chars:
            ensemble = self.crew.ensemble(secondary_chars)
            agents.append(ensemble)
            for char in secondary_chars:
                tasks.append(Task(
                    description=(
                        f"现在请代入次要角色【{char.name}】。\n"
                        f"导演意图(仅供参考):\n"
                        f"{self.state.director_intent}\n\n"
                        f"{self.state.memory.as_prompt_block()}\n\n"
                        f"给出{char.name}在这一刻的简短反应/台词。"
                    ),
                    expected_output=f"{char.name}的简短反应",
                    agent=ensemble,
                ))

        crew = Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
        )
        result = crew.kickoff()
        self.state.actor_log = str(result)
        return self.state.actor_log

    # ============================================================
    # Step 4: 一致性检测
    # ============================================================
    @listen(run_actor_interaction)
    def check_consistency(self, actor_log: str):
        """
        ConsistencyAgent 校验人设/时间线/设定冲突
        输出强制为 JSON，解析失败时默认放行避免卡死 flow。
        """
        agent = self.crew.consistency()
        char_data = json.dumps(
            [c.model_dump() for c in self.state.project.characters],
            ensure_ascii=False,
            indent=2,
        )
        foreshadow_data = json.dumps(
            [f.model_dump() for f in self.state.project.foreshadowings],
            ensure_ascii=False,
            default=str,
        )
        task = Task(
            description=(
                f"检查以下角色行动记录:\n{actor_log}\n\n"
                f"角色设定:\n{char_data}\n\n"
                f"活跃伏笔:\n{foreshadow_data}\n\n"
                "检查项：\n"
                "1. 角色行为是否符合人设\n"
                "2. 时间线是否合理\n"
                "3. 已采纳的意外事件是否'合理但意外'而非'莫名其妙'\n"
                "4. 伏笔操作是否与已有设定冲突\n\n"
                "输出 JSON: {passed, conflicts, severity}"
            ),
            expected_output="JSON 一致性报告",
            agent=agent,
        )
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
        )
        raw = str(crew.kickoff())

        # 容错解析：推理模型结构化输出不稳定时兜底
        try:
            report = ConsistencyReport(**parse_json_block(raw))
        except Exception:
            report = ConsistencyReport(
                passed=True, conflicts=[], severity="none"
            )

        self.state.consistency_report = report
        return report

    # ============================================================
    # Step 4.5: 路由——冲突严重则回退重试
    # ============================================================
    @router(check_consistency)
    def route_after_check(self, report: ConsistencyReport):
        if (
            not report.passed
            and report.severity == "major"
            and self.state.retry_count < self.max_retries
        ):
            self.state.retry_count += 1
            return "retry"
        return "proceed"

    @listen("retry")
    def retry_actor_interaction(self):
        """冲突回退：把冲突信息带回重新生成，并继续完成后续步骤"""
        conflicts_info = "\n".join(
            self.state.consistency_report.conflicts
        ) if self.state.consistency_report else ""
        print(f"⚠️ 检测到严重冲突，回退重试: {conflicts_info}")

        # 把冲突作为"禁止事项"追加到导演意图，注入下一轮角色任务
        self.state.director_intent += (
            f"\n\n【上一轮被检测出的冲突，本轮必须避免】\n"
            f"{conflicts_info}"
        )
        self.run_actor_interaction(self.rag_context)
        prose = self.write_prose()
        return self.update_memory_and_foreshadowings(prose)

    # ============================================================
    # Step 5: 润色成正式小说正文
    # ============================================================
    @listen("proceed")
    def write_prose(self):
        """
        ProseAgent 把结构化的行动日志转写成文学化的小说正文
        伏笔暗示要自然织入，意外事件要用节奏感烘托冲击力。
        """
        prose_agent = self.crew.prose(
            self.state.project.style
        )
        task = Task(
            description=(
                f"请把以下角色行动日志，改写成统一风格"
                f"('{self.state.project.style}')的正式小说正文。\n"
                f"像一个隐形在场的叙述者一样，融合对话、动作、"
                f"心理与环境描写。\n\n"
                "注意：如果有伏笔暗示，要自然地织入叙事中，"
                "不能让读者觉得刻意。如果有意外事件，"
                "要用节奏感和氛围烘托其冲击力。\n\n"
                f"角色行动日志:\n{self.state.actor_log}"
            ),
            expected_output="一段完整的小说正文",
            agent=prose_agent,
        )
        crew = Crew(
            agents=[prose_agent],
            tasks=[task],
            process=Process.sequential,
        )
        result = str(crew.kickoff())
        self.state.final_prose = result
        return result

    # ============================================================
    # Step 6: 更新记忆 + 更新伏笔状态
    # ============================================================
    @listen(write_prose)
    def update_memory_and_foreshadowings(self, prose: str):
        """
        写回记忆 + 根据 ForeshadowingAgent 的建议更新伏笔状态
        这是防止"注意力稀释导致伏笔遗忘"的关键机制。
        """
        self.state.memory.add_scene_summary(prose)

        project = self.state.project
        advance_scene_counters(project)

        # 尝试解析导演采纳的伏笔操作并应用
        try:
            director_data = parse_json_block(
                self.state.director_intent
            )
            apply_foreshadow_ops(
                project,
                director_data.get("adopted_foreshadow_ops", []),
            )
        except (ValueError, KeyError, TypeError) as exc:
            print(f"  ℹ️ 伏笔操作解析跳过: {exc}")

        print("✅ 记忆和伏笔状态已更新")
        return self.state.final_prose
