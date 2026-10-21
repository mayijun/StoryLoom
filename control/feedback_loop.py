"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

系统控制论核心模块：反馈闭环 + 统计滤波 + 整体优化

对应钱学森《工程控制论》原理：
① "反馈系统要比开环系统强" → 生成-批评-修正多轮闭环
② "存在噪声时可用统计滤波" → 多次采样 + 投票/加权聚合
③ "追求总体合理性" → 端到端质量评分作为目标函数
"""

import json
from typing import List

from crewai import Agent, Crew, Process, Task
from pydantic import BaseModel, Field


# ================================================================
# 原理①：反馈闭环（Feedback Loop）
# "不要让单个 agent 一次性输出结果直接作为最终答案（开环）；
#  引入 Critic/Verifier agent 对输出进行校验，
#  形成'生成→批评→修正'的闭环"
# ================================================================

class FeedbackResult(BaseModel):
    """反馈闭环单轮结果"""

    iteration: int
    content: str
    critique: str
    score: float                # 0~1 质量评分
    passed: bool                # 是否达到阈值
    improvements: List[str]     # 具体改进建议


class FeedbackLoop:
    """
    通用反馈闭环控制器

    工作原理：
    1. Generator Agent 生成初稿
    2. Critic Agent 评估并给出评分和改进建议
    3. 如果评分 < 阈值，将批评反馈给 Generator 重新生成
    4. 循环直到通过或达到最大迭代次数

    这比简单的"一次生成"（开环）显著提升输出质量，
    因为每一轮的误差都被反馈纠正，而非累积传递到下游。
    """

    def __init__(
        self,
        generator: Agent,
        critic: Agent,
        max_iterations: int = 3,
        quality_threshold: float = 0.7,
    ):
        self.generator = generator
        self.critic = critic
        self.max_iterations = max_iterations
        self.quality_threshold = quality_threshold
        self.history: List[FeedbackResult] = []

    def run(
        self,
        task_description: str,
        expected_output: str,
        context: str = "",
    ) -> FeedbackResult:
        """执行反馈闭环"""
        current_content = ""
        previous_critique = ""

        for i in range(self.max_iterations):
            # ---- 生成阶段 ----
            gen_prompt = task_description
            if previous_critique:
                gen_prompt += (
                    f"\n\n【上一轮反馈（请据此改进）】\n"
                    f"{previous_critique}"
                )
            if context:
                gen_prompt += f"\n\n【背景信息】\n{context}"

            gen_task = Task(
                description=gen_prompt,
                expected_output=expected_output,
                agent=self.generator,
            )
            gen_crew = Crew(
                agents=[self.generator],
                tasks=[gen_task],
                process=Process.sequential,
            )
            current_content = str(gen_crew.kickoff())

            # ---- 批评阶段 ----
            critic_prompt = (
                f"请评估以下内容的质量：\n\n{current_content}\n\n"
                f"原始要求：{task_description}\n\n"
                "请输出 JSON 格式：\n"
                "- score: 0~1 的质量评分\n"
                "- passed: 是否达标(bool)\n"
                "- critique: 总体评价\n"
                "- improvements: 具体改进建议数组\n"
                f"达标阈值: {self.quality_threshold}"
            )
            critic_task = Task(
                description=critic_prompt,
                expected_output="JSON 评估报告",
                agent=self.critic,
            )
            critic_crew = Crew(
                agents=[self.critic],
                tasks=[critic_task],
                process=Process.sequential,
            )
            raw_critique = str(critic_crew.kickoff())

            # 解析评估结果
            try:
                data = json.loads(
                    raw_critique[
                        raw_critique.find("{"):
                        raw_critique.rfind("}") + 1
                    ]
                )
                result = FeedbackResult(
                    iteration=i + 1,
                    content=current_content,
                    critique=data.get("critique", ""),
                    score=float(data.get("score", 0.5)),
                    passed=bool(data.get("passed", False)),
                    improvements=data.get("improvements", []),
                )
            except Exception:
                result = FeedbackResult(
                    iteration=i + 1,
                    content=current_content,
                    critique=raw_critique,
                    score=0.5,
                    passed=False,
                    improvements=["无法解析评估，默认不通过"],
                )

            self.history.append(result)
            print(
                f"  🔄 反馈闭环 第{i + 1}轮: "
                f"评分={result.score:.2f} "
                f"{'✅通过' if result.passed else '❌未通过'}"
            )

            if result.passed or result.score >= self.quality_threshold:
                return result

            previous_critique = (
                f"评分: {result.score}\n"
                f"评价: {result.critique}\n"
                f"改进建议:\n"
                + "\n".join(f"- {imp}" for imp in result.improvements)
            )

        # 达到最大迭代次数，返回最高分的那一轮
        best = max(self.history, key=lambda r: r.score)
        print(
            f"  ⚠️ 达到最大迭代{self.max_iterations}次，"
            f"选择最佳轮次(第{best.iteration}轮, "
            f"评分{best.score:.2f})"
        )
        return best


# ================================================================
# 原理②：冗余与统计滤波（Redundancy + Statistical Filtering）
# "让多个 agent 独立完成同一子任务，
#  再通过投票、加权融合方式聚合结果"
# ================================================================

class SamplingResult(BaseModel):
    """单次采样结果"""

    sample_id: int
    content: str
    score: float = 0.0


class StatisticalFilter:
    """
    统计滤波器：多次独立采样 + 评分筛选

    数学原理：利用误差独立同分布假设下"方差随聚合数量下降"的
    统计规律——即使单个 Agent 误差不可忽略，
    整体系统的误差期望值也可以显著降低。

    在小说场景中的应用：
    - 同一场景让角色 Agent 生成多个版本
    - 由评估 Agent 打分
    - 选择最佳版本
    """

    def __init__(
        self,
        generator: Agent,
        evaluator: Agent,
        n_samples: int = 3,
    ):
        self.generator = generator
        self.evaluator = evaluator
        self.n_samples = n_samples

    def sample_and_filter(
        self,
        task_description: str,
        expected_output: str,
    ) -> SamplingResult:
        """
        多次采样 → 独立评分 → 选择最佳

        相当于经典控制论中的"多传感器冗余 + 最优估计"：
        每次采样相当于一个独立传感器，
        评分相当于置信度权重，选择最佳相当于最优估计。
        """
        samples: List[SamplingResult] = []

        for i in range(self.n_samples):
            gen_task = Task(
                description=(
                    f"{task_description}\n\n"
                    f"（这是第{i + 1}次独立生成，"
                    f"请给出你认为最好的版本）"
                ),
                expected_output=expected_output,
                agent=self.generator,
            )
            crew = Crew(
                agents=[self.generator],
                tasks=[gen_task],
                process=Process.sequential,
            )
            content = str(crew.kickoff())
            samples.append(
                SamplingResult(sample_id=i + 1, content=content)
            )

        # 批量评分
        all_texts = "\n\n---\n\n".join(
            f"【版本{s.sample_id}】\n{s.content}" for s in samples
        )
        eval_task = Task(
            description=(
                f"以下是同一任务的{self.n_samples}个独立生成版本，"
                f"请为每个版本打分(0~1)：\n\n{all_texts}\n\n"
                f"原始要求：{task_description}\n\n"
                "输出 JSON 数组: "
                '[{"sample_id": 1, "score": 0.8}, ...]'
            ),
            expected_output="JSON 评分数组",
            agent=self.evaluator,
        )
        eval_crew = Crew(
            agents=[self.evaluator],
            tasks=[eval_task],
            process=Process.sequential,
        )
        raw = str(eval_crew.kickoff())

        try:
            scores_data = json.loads(
                raw[raw.find("["): raw.rfind("]") + 1]
            )
            for sd in scores_data:
                sid = sd.get("sample_id", 0)
                for s in samples:
                    if s.sample_id == sid:
                        s.score = float(sd.get("score", 0.5))
        except Exception:
            for s in samples:
                s.score = 0.5

        best = max(samples, key=lambda s: s.score)
        print(
            f"  📊 统计滤波: {self.n_samples}个采样, "
            f"分数={[f'{s.score:.2f}' for s in samples]}, "
            f"选择版本{best.sample_id}(分数{best.score:.2f})"
        )
        return best


# ================================================================
# 原理③：整体质量评估（End-to-End Quality Score）
# "以整个 pipeline 的端到端任务成功率为目标函数来设计系统，
#  某些环节可以容忍较大误差，只要后续环节能够纠正"
# ================================================================

class SceneQualityReport(BaseModel):
    """场景级端到端质量评估报告"""

    overall_score: float                # 整体评分 0~1
    character_consistency: float        # 角色一致性
    plot_logic: float                   # 情节逻辑性
    surprise_effectiveness: float       # 意外效果
    foreshadowing_integration: float    # 伏笔融合度
    prose_quality: float                # 文笔质量
    weakest_dimension: str              # 最薄弱环节
    recommendations: List[str]          # 整体改进建议


class EndToEndEvaluator:
    """
    端到端质量评估器

    关键设计理念：
    "不要孤立地优化每个 Agent 的'单轮正确率'，
     而应以整个 pipeline 的端到端任务成功率为目标函数"

    这意味着：即使某个 Agent（如群演 Agent）的单次输出质量一般，
    只要最终小说正文质量高，系统就是成功的。
    """

    def __init__(self, evaluator_agent: Agent):
        self.evaluator = evaluator_agent

    def evaluate_scene(
        self,
        final_prose: str,
        scene_brief: str,
        character_data: str,
        foreshadowing_data: str,
    ) -> SceneQualityReport:
        """评估最终输出的端到端质量"""
        task = Task(
            description=(
                f"请对以下小说场景做端到端质量评估：\n\n"
                f"【最终正文】\n{final_prose}\n\n"
                f"【原始场景要求】\n{scene_brief}\n\n"
                f"【角色设定】\n{character_data}\n\n"
                f"【伏笔状态】\n{foreshadowing_data}\n\n"
                "请输出 JSON 格式的评估报告，字段：\n"
                "- overall_score (0~1)\n"
                "- character_consistency (0~1)\n"
                "- plot_logic (0~1)\n"
                "- surprise_effectiveness (0~1)\n"
                "- foreshadowing_integration (0~1)\n"
                "- prose_quality (0~1)\n"
                "- weakest_dimension (最薄弱环节名称)\n"
                "- recommendations (改进建议数组)"
            ),
            expected_output="JSON 质量评估报告",
            agent=self.evaluator,
        )
        crew = Crew(
            agents=[self.evaluator],
            tasks=[task],
            process=Process.sequential,
        )
        raw = str(crew.kickoff())

        try:
            data = json.loads(
                raw[raw.find("{"): raw.rfind("}") + 1]
            )
            return SceneQualityReport(**data)
        except Exception:
            return SceneQualityReport(
                overall_score=0.5,
                character_consistency=0.5,
                plot_logic=0.5,
                surprise_effectiveness=0.5,
                foreshadowing_integration=0.5,
                prose_quality=0.5,
                weakest_dimension="unknown",
                recommendations=["评估解析失败"],
            )
