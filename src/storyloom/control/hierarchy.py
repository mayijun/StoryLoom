"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

分层大系统管控 + 人机结合模块

对应钱学森原理：
⑥ 分层/大系统式组织管理：
   "设置 Orchestrator/总控 agent 负责任务分解、调度与结果整合，
    类似'总设计师'角色"
⑦ 人机结合的综合集成：
   "以人为主、人机结合，从定性到定量的综合集成法"

参考：
- 钱学森航天系统工程"总设计师 + 行政指挥两条线"
- 开放的复杂巨系统理论
"""

from enum import Enum
from typing import Callable, Dict, List, Optional

from storyloom.control.feedback_loop import SceneQualityReport
from storyloom.control.robustness import AgentOutput, SensitivityAnalyzer, SensitivityTier


class ControlDecision(str, Enum):
    """总控制器的决策类型"""

    PASS = "pass"                   # 直接放行
    FEEDBACK_LOOP = "feedback_loop"  # 启动反馈闭环
    MULTI_SAMPLE = "multi_sample"   # 多次采样滤波
    HUMAN_REVIEW = "human_review"   # 交人工审核
    REJECT_RETRY = "reject_retry"   # 拒绝并要求整体重试


class SystemOrchestrator:
    """
    系统总控制器（"总设计师"角色）

    职责：
    1. 根据灵敏度分析，决定每个 Agent 步骤使用哪种控制策略
    2. 在关键节点设置"质量闸门"
    3. 追踪整体质量指标，必要时触发全局回退
    4. 管理人工审核节点

    这对应钱学森航天工程中的"总设计师"：
    不亲自做每个子系统，但对整体质量负责，
    统筹各子系统的输出，在顶层把关整体一致性。
    """

    def __init__(
        self,
        human_review_callback: Optional[Callable] = None,
        auto_mode: bool = True,
    ):
        self.human_review_callback = human_review_callback
        self.auto_mode = auto_mode
        self.quality_history: List[SceneQualityReport] = []
        self.decision_log: List[Dict] = []

    def decide_control_strategy(self, agent_role: str) -> ControlDecision:
        """
        根据灵敏度等级决定控制策略

        高杠杆 Agent → 多重控制
        低杠杆 Agent → 轻量通过
        """
        profile = SensitivityAnalyzer.get_profile(agent_role)

        if profile.sensitivity_tier == SensitivityTier.CRITICAL:
            if profile.n_samples > 1:
                decision = ControlDecision.MULTI_SAMPLE
            else:
                decision = ControlDecision.FEEDBACK_LOOP
        elif profile.sensitivity_tier == SensitivityTier.HIGH:
            if profile.needs_feedback_loop:
                decision = ControlDecision.FEEDBACK_LOOP
            else:
                decision = ControlDecision.MULTI_SAMPLE
        elif profile.needs_human_review and not self.auto_mode:
            decision = ControlDecision.HUMAN_REVIEW
        else:
            decision = ControlDecision.PASS

        self.decision_log.append({
            "agent_role": agent_role,
            "sensitivity": profile.sensitivity_tier.value,
            "decision": decision.value,
        })

        return decision

    def quality_gate(
        self,
        agent_role: str,
        output: AgentOutput,
        threshold: float = 0.5,
    ) -> bool:
        """
        质量闸门：关键节点的通过/拦截决策

        低于阈值的输出会被拦截并触发重试，
        这防止低质量输出向下游传播（误差级联控制）。
        """
        if output.confidence < threshold:
            print(
                f"  🚫 质量闸门拦截: [{agent_role}] "
                f"置信度{output.confidence:.2f} < "
                f"阈值{threshold}"
            )
            return False

        if output.warnings:
            print(
                f"  ⚠️ 质量闸门警告: [{agent_role}] "
                f"{len(output.warnings)}个潜在问题"
            )
            for w in output.warnings:
                print(f"     - {w}")

        return True

    # ================================================================
    # 原理⑦：人机结合的综合集成
    # ================================================================

    def human_review_gate(
        self,
        agent_role: str,
        content: str,
        context: str = "",
    ) -> Dict:
        """
        人工审核闸门

        在以下情况触发：
        1. 一致性检测发现重大冲突
        2. 意外事件的严重程度为 major
        3. 整体质量评分连续下降
        4. 用户手动标记需要审核的场景

        返回：{"approved": bool, "feedback": str, "edits": str}
        """
        if self.auto_mode:
            print(
                f"  👤 [自动模式] 跳过人工审核: [{agent_role}]"
            )
            return {
                "approved": True,
                "feedback": "自动通过",
                "edits": "",
            }

        if self.human_review_callback:
            return self.human_review_callback(
                agent_role, content, context
            )

        # 默认：命令行交互式审核
        print(f"\n{'=' * 50}")
        print(f"👤 人工审核请求: [{agent_role}]")
        print(f"{'=' * 50}")
        print(f"内容:\n{content[:500]}...")
        if context:
            print(f"\n背景:\n{context[:300]}...")

        approval = input("\n批准? (y/n/e[编辑]): ").strip().lower()

        if approval == "y":
            return {
                "approved": True,
                "feedback": "人工审核通过",
                "edits": "",
            }
        if approval == "e":
            edits = input("请输入修改意见: ")
            return {
                "approved": True,
                "feedback": f"人工修改: {edits}",
                "edits": edits,
            }
        feedback = input("拒绝理由: ")
        return {
            "approved": False,
            "feedback": feedback,
            "edits": "",
        }

    def track_quality_trend(self, report: SceneQualityReport) -> bool:
        """
        追踪质量趋势：连续下降则触发全局预警

        这是系统级的"自适应、自校正"机制：
        "当系统特性变化缓慢时，可以采取自适应、
         自校正等方法跟踪这些变化。"
        """
        self.quality_history.append(report)

        if len(self.quality_history) >= 3:
            recent = [
                r.overall_score for r in self.quality_history[-3:]
            ]
            if all(
                recent[i] > recent[i + 1]
                for i in range(len(recent) - 1)
            ):
                print(
                    f"  📉 质量连续下降趋势: "
                    f"{[f'{s:.2f}' for s in recent]}"
                )
                print(
                    f"     最薄弱环节: {report.weakest_dimension}"
                )
                print(
                    "     建议: 对该环节加强控制或切换更强模型"
                )
                return False  # 触发预警

        return True  # 质量稳定

    def print_decision_log(self):
        """打印控制决策日志"""
        print("\n📋 控制决策日志（总设计师记录）：")
        for entry in self.decision_log:
            emoji = {
                "pass": "✅",
                "feedback_loop": "🔄",
                "multi_sample": "📊",
                "human_review": "👤",
                "reject_retry": "🚫",
            }.get(entry["decision"], "❓")
            print(
                f"  {emoji} {entry['agent_role']:18s} "
                f"灵敏度={entry['sensitivity']:8s} "
                f"→ {entry['decision']}"
            )
