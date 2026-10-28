"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

带系统控制论改进的场景生成 Flow

整合 7 大控制论原理：
① 反馈闭环 ② 统计滤波 ③ 整体优化
④ 灵敏度分析 ⑤ 解耦控制 ⑥ 分层管控 ⑦ 人机结合

关键改进点：
- 导演 Agent: 反馈闭环 + 多次采样（灵敏度=CRITICAL）
- 意外 Agent: 多次采样供导演选择（灵敏度=HIGH）
- 群演 Agent: 单次直接通过（灵敏度=LOW）
- 润色 Agent: 反馈闭环（灵敏度=MEDIUM）
- 全局: 端到端质量评估 + 质量趋势追踪
"""

import json
from typing import List, Literal, Optional

from crewai import Crew, Process, Task
from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel, Field

from storyloom.crews.scene_crew.crew import SceneCrew
from storyloom.models import ForeshadowStatus, NovelProject
from storyloom.control.feedback_loop import (
    EndToEndEvaluator,
    FeedbackLoop,
    StatisticalFilter,
)
from storyloom.control.hierarchy import ControlDecision, SystemOrchestrator
from storyloom.control.robustness import AgentOutput, SensitivityAnalyzer
from storyloom.flows.scene_flow import (
    advance_scene_counters,
    apply_foreshadow_ops,
)
from storyloom.memory import CoreMemory, SimpleRAGMemory


class ConsistencyReport(BaseModel):
    passed: bool
    conflicts: List[str] = Field(default_factory=list)
    severity: Literal["none", "minor", "major"] = "none"


class ControlledSceneFlowState(BaseModel):
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
    # 控制论增强字段
    e2e_quality_score: float = 0.0
    control_decisions: List[str] = Field(default_factory=list)


class ControlledSceneFlow(Flow[ControlledSceneFlowState]):
    """
    带系统控制论增强的场景生成 Flow

    与基础版的关键区别：
    1. 每个步骤前先查灵敏度，决定控制策略
    2. 高杠杆步骤自动启用反馈闭环或多次采样
    3. 最后做端到端质量评估并追踪趋势
    4. 关键节点可触发人工审核
    """

    def __init__(
        self,
        project: NovelProject,
        memory: CoreMemory,
        rag: SimpleRAGMemory,
        crew: SceneCrew,
        orchestrator: SystemOrchestrator,
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
        self.orchestrator = orchestrator
        self.present_characters = present_characters
        self.max_retries = max_retries
        self.rag_context = ""

    # ============================================================
    # Step 0a: SurpriseAgent（灵敏度=HIGH → 多次采样）
    # ============================================================
    @start()
    def propose_surprise(self):
        """意外 Agent: 多次采样，供导演选择最佳提案"""
        decision = self.orchestrator.decide_control_strategy("surprise")
        profile = SensitivityAnalyzer.get_profile("surprise")

        surprise_agent = self.crew.surprise()

        project = self.state.project
        scenes_since_last = (
            project.scene_count - project.last_major_surprise_scene
        )
        cooldown_hint = ""
        if scenes_since_last < project.surprise_cooldown:
            cooldown_hint = "\n⚠️ 冷却期中，本场景建议不要有重大意外。"

        active_fs = [
            f"- [{f.foreshadow_id}] {f.description}"
            for f in project.foreshadowings
            if f.status
            in (ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED)
        ]
        fs_context = (
            "\n".join(active_fs) if active_fs else "（无活跃伏笔）"
        )

        task_desc = (
            f"故事: {project.title}\n"
            f"{self.state.memory.as_prompt_block()}\n"
            f"场景: {self.state.scene_brief}\n"
            f"{cooldown_hint}\n"
            f"活跃伏笔:\n{fs_context}\n\n"
            "评估是否需要意外元素，输出 JSON 提案。"
        )

        if decision == ControlDecision.MULTI_SAMPLE:
            evaluator = self.crew.consistency()
            sf = StatisticalFilter(
                generator=surprise_agent,
                evaluator=evaluator,
                n_samples=profile.n_samples,
            )
            best = sf.sample_and_filter(task_desc, "JSON 意外提案")
            self.state.surprise_proposal = best.content
        else:
            task = Task(
                description=task_desc,
                expected_output="JSON 意外提案",
                agent=surprise_agent,
            )
            crew = Crew(
                agents=[surprise_agent],
                tasks=[task],
                process=Process.sequential,
            )
            self.state.surprise_proposal = str(crew.kickoff())

        return self.state.surprise_proposal

    # ============================================================
    # Step 0b: ForeshadowingAgent（灵敏度=HIGH → 反馈闭环）
    # ============================================================
    @listen(propose_surprise)
    def propose_foreshadowing_ops(self, surprise_proposal: str):
        """伏笔 Agent: 反馈闭环确保建议合理"""
        decision = self.orchestrator.decide_control_strategy(
            "foreshadowing"
        )

        foreshadowing_agent = self.crew.foreshadowing()

        project = self.state.project
        fs_table = (
            "\n".join(
                f"- [{f.foreshadow_id}] {f.description} "
                f"(状态:{f.status.value})"
                for f in project.foreshadowings
                if f.status
                in (
                    ForeshadowStatus.PLANTED,
                    ForeshadowStatus.REINFORCED,
                )
            )
            or "（无活跃伏笔）"
        )

        task_desc = (
            f"故事: {project.title}\n"
            f"{self.state.memory.as_prompt_block()}\n"
            f"场景: {self.state.scene_brief}\n\n"
            f"伏笔状态:\n{fs_table}\n\n"
            f"意外提案:\n{surprise_proposal}\n\n"
            "输出伏笔操作建议 JSON。"
        )

        if decision == ControlDecision.FEEDBACK_LOOP:
            critic = self.crew.consistency()
            loop = FeedbackLoop(
                generator=foreshadowing_agent,
                critic=critic,
                max_iterations=2,
                quality_threshold=0.7,
            )
            result = loop.run(task_desc, "JSON 伏笔操作")
            self.state.foreshadowing_ops = result.content
        else:
            task = Task(
                description=task_desc,
                expected_output="JSON 伏笔操作",
                agent=foreshadowing_agent,
            )
            crew = Crew(
                agents=[foreshadowing_agent],
                tasks=[task],
                process=Process.sequential,
            )
            self.state.foreshadowing_ops = str(crew.kickoff())

        return self.state.foreshadowing_ops

    # ============================================================
    # Step 1: 导演Agent（灵敏度=CRITICAL → 多采样+反馈闭环）
    # ============================================================
    @listen(propose_foreshadowing_ops)
    def plan_scene(self, foreshadowing_ops: str):
        """
        导演 Agent: 灵敏度最高，双重控制

        原理④: "导演的一个错误决策会影响整个场景所有角色"
        → 必须多重校验
        """
        decision = self.orchestrator.decide_control_strategy("director")

        director = self.crew.director()
        task_desc = (
            f"故事: {self.state.project.title}\n"
            f"{self.state.memory.as_prompt_block()}\n"
            f"场景: {self.state.scene_brief}\n\n"
            f"意外提案:\n{self.state.surprise_proposal}\n\n"
            f"伏笔建议:\n{foreshadowing_ops}\n\n"
            "综合以上，输出最终场景意图包 JSON。"
        )

        if decision in (
            ControlDecision.MULTI_SAMPLE,
            ControlDecision.FEEDBACK_LOOP,
        ):
            critic = self.crew.consistency()
            loop = FeedbackLoop(
                generator=director,
                critic=critic,
                max_iterations=2,
                quality_threshold=0.75,
            )
            result = loop.run(task_desc, "JSON 场景意图包")
            self.state.director_intent = result.content
        else:
            task = Task(
                description=task_desc,
                expected_output="JSON 场景意图包",
                agent=director,
            )
            crew = Crew(
                agents=[director],
                tasks=[task],
                process=Process.sequential,
            )
            self.state.director_intent = str(crew.kickoff())

        # 质量闸门
        output = AgentOutput(
            agent_role="director",
            content=self.state.director_intent,
            confidence=0.8,
            dependencies_used=[
                "outline", "surprise", "foreshadowing",
            ],
        )
        self.orchestrator.quality_gate("director", output)

        return self.state.director_intent

    # ============================================================
    # Step 2: RAG 检索（无 Agent，无需控制）
    # ============================================================
    @listen(plan_scene)
    def gather_rag_context(self, director_intent: str):
        query = self.state.scene_brief + " " + director_intent
        docs = self.rag.query(query, n_results=3)
        self.rag_context = "\n".join(docs) if docs else "（无）"
        return self.rag_context

    # ============================================================
    # Step 3: 角色互动
    # 主角=HIGH(反馈闭环)，群演=LOW(直接通过)
    # ============================================================
    @listen(gather_rag_context)
    def run_actor_interaction(self, rag_context: str):
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

        all_outputs = []

        # 主角：反馈闭环（灵敏度=HIGH）
        for char in primary_chars:
            agent = self.crew.protagonist(char)
            task_desc = (
                f"导演意图(参考):\n{self.state.director_intent}\n\n"
                f"背景:\n{rag_context}\n\n"
                f"{self.state.memory.as_prompt_block()}\n\n"
                f"以【{char.name}】身份行动。"
            )

            decision = self.orchestrator.decide_control_strategy(
                "protagonist"
            )
            if decision == ControlDecision.FEEDBACK_LOOP:
                critic = self.crew.consistency()
                loop = FeedbackLoop(
                    generator=agent,
                    critic=critic,
                    max_iterations=2,
                    quality_threshold=0.7,
                )
                result = loop.run(
                    task_desc, f"{char.name}的行动记录"
                )
                all_outputs.append(result.content)
            else:
                task = Task(
                    description=task_desc,
                    expected_output=f"{char.name}的行动",
                    agent=agent,
                )
                crew = Crew(
                    agents=[agent],
                    tasks=[task],
                    process=Process.sequential,
                )
                all_outputs.append(str(crew.kickoff()))

        # 群演：直接通过（灵敏度=LOW）
        if secondary_chars:
            self.orchestrator.decide_control_strategy("ensemble")
            ensemble = self.crew.ensemble(secondary_chars)
            for char in secondary_chars:
                task = Task(
                    description=(
                        f"代入【{char.name}】简短反应。\n"
                        f"{self.state.memory.as_prompt_block()}"
                    ),
                    expected_output=f"{char.name}的反应",
                    agent=ensemble,
                )
                crew = Crew(
                    agents=[ensemble],
                    tasks=[task],
                    process=Process.sequential,
                )
                all_outputs.append(str(crew.kickoff()))

        self.state.actor_log = "\n\n---\n\n".join(all_outputs)
        return self.state.actor_log

    # ============================================================
    # Step 4: 一致性检测（灵敏度=CRITICAL → 多次采样投票）
    # ============================================================
    @listen(run_actor_interaction)
    def check_consistency(self, actor_log: str):
        """
        一致性检测：多次采样投票

        原理④: "如果漏报冲突 → 永久性设定矛盾"
        → 多次独立检测，投票决定是否真有冲突
        """
        self.orchestrator.decide_control_strategy("consistency")
        profile = SensitivityAnalyzer.get_profile("consistency")

        char_data = json.dumps(
            [c.model_dump() for c in self.state.project.characters],
            ensure_ascii=False,
        )

        reports = []
        for _ in range(profile.n_samples):
            agent = self.crew.consistency()
            task = Task(
                description=(
                    f"检查行动记录:\n{actor_log}\n\n"
                    f"角色设定:\n{char_data}\n\n"
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
            try:
                data = json.loads(
                    raw[raw.find("{"): raw.rfind("}") + 1]
                )
                reports.append(ConsistencyReport(**data))
            except Exception:
                reports.append(ConsistencyReport(
                    passed=True, conflicts=[], severity="none"
                ))

        # 📊 投票聚合（统计滤波）
        n_passed = sum(1 for r in reports if r.passed)
        majority_pass = n_passed > len(reports) / 2

        all_conflicts = []
        for r in reports:
            all_conflicts.extend(r.conflicts)
        unique_conflicts = list(set(all_conflicts))

        worst_severity = "none"
        for r in reports:
            if r.severity == "major":
                worst_severity = "major"
                break
            if r.severity == "minor":
                worst_severity = "minor"

        final_report = ConsistencyReport(
            passed=majority_pass,
            conflicts=unique_conflicts,
            severity=worst_severity,
        )

        print(
            f"  📊 一致性投票: {n_passed}/{len(reports)}通过 "
            f"→ {'✅' if majority_pass else '❌'} "
            f"(冲突{len(unique_conflicts)}项)"
        )

        self.state.consistency_report = final_report
        return final_report

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
        """一致性检测未通过 → 回退重跑并继续完成后续步骤"""
        conflicts_info = "\n".join(
            self.state.consistency_report.conflicts
        ) if self.state.consistency_report else ""
        print(f"⚠️ 一致性检测未通过，回退重试: {conflicts_info}")

        self.state.director_intent += (
            f"\n\n【上一轮被检测出的冲突，本轮必须避免】\n"
            f"{conflicts_info}"
        )
        self.run_actor_interaction(self.rag_context)
        prose = self.write_prose()
        return self.evaluate_and_update(prose)

    # ============================================================
    # Step 5: 润色（灵敏度=MEDIUM → 反馈闭环）
    # ============================================================
    @listen("proceed")
    def write_prose(self):
        decision = self.orchestrator.decide_control_strategy("prose")
        prose_agent = self.crew.prose(
            self.state.project.style
        )

        task_desc = (
            f"把行动日志改写成'{self.state.project.style}'"
            f"风格正文：\n\n{self.state.actor_log}"
        )

        if decision == ControlDecision.FEEDBACK_LOOP:
            critic = self.crew.consistency()
            loop = FeedbackLoop(
                generator=prose_agent,
                critic=critic,
                max_iterations=2,
                quality_threshold=0.75,
            )
            result = loop.run(task_desc, "小说正文")
            self.state.final_prose = result.content
        else:
            task = Task(
                description=task_desc,
                expected_output="小说正文",
                agent=prose_agent,
            )
            crew = Crew(
                agents=[prose_agent],
                tasks=[task],
                process=Process.sequential,
            )
            self.state.final_prose = str(crew.kickoff())

        return self.state.final_prose

    # ============================================================
    # Step 6: 端到端评估 + 记忆更新 + 质量趋势追踪
    # ============================================================
    @listen(write_prose)
    def evaluate_and_update(self, prose: str):
        """
        原理③: 端到端质量评估
        原理⑥: 质量趋势追踪（自适应）
        """
        evaluator_agent = self.crew.consistency()
        e2e = EndToEndEvaluator(evaluator_agent)
        report = e2e.evaluate_scene(
            final_prose=prose,
            scene_brief=self.state.scene_brief,
            character_data=json.dumps(
                [
                    c.model_dump()
                    for c in self.state.project.characters
                ],
                ensure_ascii=False,
            ),
            foreshadowing_data=json.dumps(
                [
                    f.model_dump()
                    for f in self.state.project.foreshadowings
                ],
                ensure_ascii=False,
                default=str,
            ),
        )

        self.state.e2e_quality_score = report.overall_score
        print(f"\n  📈 端到端质量评分: {report.overall_score:.2f}")
        print(f"     角色一致性: {report.character_consistency:.2f}")
        print(f"     情节逻辑: {report.plot_logic:.2f}")
        print(f"     意外效果: {report.surprise_effectiveness:.2f}")
        print(f"     伏笔融合: {report.foreshadowing_integration:.2f}")
        print(f"     文笔质量: {report.prose_quality:.2f}")
        print(f"     最薄弱: {report.weakest_dimension}")

        # 质量趋势追踪
        self.orchestrator.track_quality_trend(report)

        # 更新记忆与场景计数
        project = self.state.project
        self.state.memory.add_scene_summary(prose)
        advance_scene_counters(project)

        # 应用导演采纳的伏笔操作
        try:
            director_data = json.loads(
                self.state.director_intent[
                    self.state.director_intent.find("{"):
                    self.state.director_intent.rfind("}") + 1
                ]
            )
            apply_foreshadow_ops(
                project,
                director_data.get("adopted_foreshadow_ops", []),
            )
        except (ValueError, KeyError, TypeError) as exc:
            print(f"  ℹ️ 伏笔操作解析跳过: {exc}")

        # 打印控制决策日志
        self.orchestrator.print_decision_log()

        print("✅ 完成（含系统控制论增强）")
        return self.state.final_prose
