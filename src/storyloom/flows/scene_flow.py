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
        is_regenerate: bool = False,
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
        # 重跑同一编号场景时：不递增 scene_count，不推进伏笔沉睡计数
        self.is_regenerate = is_regenerate

    def _director_constraints(self) -> str:
        """提取导演已采纳的伏笔/意外，供一致性与润色步骤使用

        导演输出本应是 JSON 意图包；解析失败时退回原文，
        保证后续步骤仍能拿到导演意图而不是空串。
        """
        intent = self.state.director_intent or ""
        try:
            data = parse_json_block(intent)
        except (ValueError, TypeError):
            return intent

        parts = []
        surprise = data.get("adopted_surprise")
        if surprise:
            parts.append(
                "意外事件: " + json.dumps(surprise, ensure_ascii=False)
            )
        ops = data.get("adopted_foreshadow_ops") or []
        if ops:
            parts.append(
                "伏笔操作: " + json.dumps(ops, ensure_ascii=False)
            )
        return "\n".join(parts)

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
        # 单 Agent 单任务：Flow 已负责时序，直接用 Agent.kickoff 省掉 Crew 开销。
        # 提示词来自数据库中的 surprise_proposal 任务，与标准 Crew 共用一份。
        output = surprise_agent.kickoff(
            self.crew.task_prompt(
                "surprise_proposal",
                project_title=project.title,
                memory_block=self.state.memory.as_prompt_block(),
                scene_brief=self.state.scene_brief,
                cooldown_hint=cooldown_hint,
                active_foreshadowings=foreshadow_context,
            )
        )
        result = str(output.raw)
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
        output = foreshadowing_agent.kickoff(
            self.crew.task_prompt(
                "foreshadowing_ops",
                project_title=project.title,
                memory_block=self.state.memory.as_prompt_block(),
                scene_brief=self.state.scene_brief,
                present_characters=", ".join(self.present_characters),
                foreshadow_table=foreshadow_status,
                urgent_alerts=alerts,
                surprise_proposal=surprise_proposal,
            )
        )
        result = str(output.raw)
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
        output = director.kickoff(
            self.crew.task_prompt(
                "director_plan",
                project_title=self.state.project.title,
                memory_block=self.state.memory.as_prompt_block(),
                scene_brief=self.state.scene_brief,
                surprise_proposal=self.state.surprise_proposal,
                foreshadowing_ops=foreshadowing_ops,
            )
        )
        self.state.director_intent = str(output.raw)
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
                description=self.crew.task_prompt(
                    "actor_interaction",
                    focus_instruction=(
                        f"请以【{char.name}】的身份，给出这一刻的"
                        f"内心想法、台词和行动。\n"
                        f"简洁、符合人设，只写行动日志式的描述。"
                    ),
                    director_intent=self.state.director_intent,
                    rag_context=rag_context,
                    memory_block=self.state.memory.as_prompt_block(),
                    character_name=char.name,
                ),
                expected_output=self.crew.task_expected_output(
                    "actor_interaction", character_name=char.name
                ),
                agent=agent,
            ))

        # 所有次要角色合并给一个群演 Agent
        if secondary_chars:
            ensemble = self.crew.ensemble(secondary_chars)
            agents.append(ensemble)
            for char in secondary_chars:
                tasks.append(Task(
                    description=self.crew.task_prompt(
                        "actor_interaction",
                        focus_instruction=(
                            f"现在请代入次要角色【{char.name}】。\n"
                            f"只写这一个角色的台词与动作，"
                            f"不要替其他角色发言。\n"
                            f"给出{char.name}在这一刻的简短反应/台词。"
                        ),
                        director_intent=self.state.director_intent,
                        rag_context=rag_context,
                        memory_block=self.state.memory.as_prompt_block(),
                        character_name=char.name,
                    ),
                    expected_output=self.crew.task_expected_output(
                        "actor_interaction", character_name=char.name
                    ),
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
        # 结构化输出交给 CrewAI 的 response_format，避免手工截取 JSON
        try:
            output = agent.kickoff(
                self.crew.task_prompt(
                    "consistency_check",
                    actor_log=actor_log,
                    character_data=char_data,
                    foreshadow_data=foreshadow_data,
                    director_constraints=(
                        self._director_constraints() or "（无）"
                    ),
                ),
                response_format=ConsistencyReport,
            )
        except Exception as exc:
            # 部分模型不支持 json_schema 响应格式（如 DeepSeek 返回 400），
            # 一致性检测属于附加校验，失败时放行，避免整个场景生成失败。
            print(f"⚠️ 一致性检测调用失败，放行本场景: {exc}")
            report = ConsistencyReport(
                passed=True, conflicts=[], severity="none"
            )
            self.state.consistency_report = report
            return report

        # 转换失败时退回手工解析，仍失败则放行，避免卡死 Flow
        report = output.pydantic
        if not isinstance(report, ConsistencyReport):
            try:
                report = ConsistencyReport(**parse_json_block(str(output.raw)))
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
        output = prose_agent.kickoff(
            self.crew.task_prompt(
                "prose_polish",
                style=self.state.project.style,
                director_constraints=(
                    self._director_constraints() or "（无）"
                ),
                actor_log=self.state.actor_log,
            )
        )
        result = str(output.raw)
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
        # 重跑同一编号场景时不推进计数（scene_count 不递增，伏笔沉睡不推进）
        if not self.is_regenerate:
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
