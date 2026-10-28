"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

鲁棒性与解耦控制模块

对应钱学森原理：
④ 鲁棒性与灵敏度分析："分析哪个 Agent 的输出误差对最终结果的
   灵敏度最高（即误差传播系数最大），针对这些'高杠杆'节点加强冗余
   校验或引入人工审核，而非平均分配资源给所有 Agent"
⑤ 解耦/非互相影响控制："设计系统使各变量/子系统互不干扰，
   误差不会相互耦合放大"

参考：《工程控制论》专门有"不互相影响的控制"章节
"""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ================================================================
# 原理④：灵敏度分析（Sensitivity Analysis）
# ================================================================

class SensitivityTier(str, Enum):
    """灵敏度等级：误差在此节点的传播系数"""

    CRITICAL = "critical"       # 误差传播系数极高，必须多重校验
    HIGH = "high"               # 误差传播较大，需要反馈闭环
    MEDIUM = "medium"           # 误差可被下游部分纠正
    LOW = "low"                 # 误差影响有限，可容忍


class AgentSensitivityProfile(BaseModel):
    """单个 Agent 的灵敏度画像"""

    agent_role: str
    sensitivity_tier: SensitivityTier
    error_propagation_to: List[str]     # 误差会传播到哪些下游
    recommended_controls: List[str]     # 推荐的控制措施
    n_samples: int = 1                  # 建议采样次数
    needs_feedback_loop: bool = False   # 是否需要反馈闭环
    needs_human_review: bool = False    # 是否需要人工审核


class SensitivityAnalyzer:
    """
    灵敏度分析器：为每个 Agent 角色计算灵敏度等级

    核心思想：不同 Agent 的"杠杆效应"不同——
    导演 Agent 的一个错误决策会影响整个场景所有角色，
    但群演 Agent 的一句台词说错了影响很小。

    因此资源分配应该不均等：
    高杠杆 Agent → 多次采样 + 反馈闭环 + 可能人工审核
    低杠杆 Agent → 单次生成就够了
    """

    PROFILES: Dict[str, AgentSensitivityProfile] = {
        "director": AgentSensitivityProfile(
            agent_role="director",
            sensitivity_tier=SensitivityTier.CRITICAL,
            error_propagation_to=[
                "所有角色Agent", "伏笔状态", "意外事件", "最终正文",
            ],
            recommended_controls=[
                "反馈闭环(3轮)",
                "多次采样取最佳",
                "一致性Agent后置校验",
            ],
            n_samples=2,
            needs_feedback_loop=True,
        ),
        "protagonist": AgentSensitivityProfile(
            agent_role="protagonist",
            sensitivity_tier=SensitivityTier.HIGH,
            error_propagation_to=["情节走向", "其他角色反应", "正文"],
            recommended_controls=[
                "反馈闭环(2轮)",
                "人设一致性校验",
            ],
            n_samples=1,
            needs_feedback_loop=True,
        ),
        "surprise": AgentSensitivityProfile(
            agent_role="surprise",
            sensitivity_tier=SensitivityTier.HIGH,
            error_propagation_to=["情节走向", "伏笔状态", "读者体验"],
            recommended_controls=[
                "导演审批",
                "一致性Agent校验",
                "多次采样供导演选择",
            ],
            n_samples=3,
            needs_feedback_loop=False,
        ),
        "foreshadowing": AgentSensitivityProfile(
            agent_role="foreshadowing",
            sensitivity_tier=SensitivityTier.HIGH,
            error_propagation_to=["长期情节一致性", "回收质量"],
            recommended_controls=[
                "显式状态机约束",
                "一致性Agent校验",
            ],
            n_samples=1,
            needs_feedback_loop=True,
        ),
        "ensemble": AgentSensitivityProfile(
            agent_role="ensemble",
            sensitivity_tier=SensitivityTier.LOW,
            error_propagation_to=["当前场景氛围"],
            recommended_controls=["基本格式校验即可"],
            n_samples=1,
            needs_feedback_loop=False,
        ),
        "consistency": AgentSensitivityProfile(
            agent_role="consistency",
            sensitivity_tier=SensitivityTier.CRITICAL,
            error_propagation_to=[
                "如果漏报冲突→永久性设定矛盾",
                "如果误报冲突→浪费重试资源",
            ],
            recommended_controls=[
                "使用结构化输出最稳定的模型",
                "多次采样投票决定是否真有冲突",
            ],
            n_samples=2,
            needs_feedback_loop=False,
        ),
        "prose": AgentSensitivityProfile(
            agent_role="prose",
            sensitivity_tier=SensitivityTier.MEDIUM,
            error_propagation_to=["读者体验", "文风一致性"],
            recommended_controls=["反馈闭环(2轮)"],
            n_samples=1,
            needs_feedback_loop=True,
        ),
    }

    @classmethod
    def get_profile(cls, role: str) -> AgentSensitivityProfile:
        return cls.PROFILES.get(
            role,
            AgentSensitivityProfile(
                agent_role=role,
                sensitivity_tier=SensitivityTier.MEDIUM,
                error_propagation_to=["未知"],
                recommended_controls=["默认单次生成"],
            ),
        )

    @classmethod
    def print_sensitivity_map(cls):
        """打印完整的灵敏度地图，帮助理解资源分配逻辑"""
        print("\n" + "=" * 70)
        print("🎛️  系统灵敏度分析（灵感来源：钱学森工程控制论）")
        print("   '针对高杠杆节点加强冗余校验，而非平均分配资源'")
        print("=" * 70)

        tier_emoji = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
        }

        for role, profile in cls.PROFILES.items():
            emoji = tier_emoji.get(
                profile.sensitivity_tier.value, "⚪"
            )
            controls = " | ".join(profile.recommended_controls)
            print(
                f"\n  {emoji} {role:18s} "
                f"灵敏度={profile.sensitivity_tier.value:8s} "
                f"采样={profile.n_samples}次 "
                f"闭环={'✅' if profile.needs_feedback_loop else '❌'}"
            )
            print(f"     误差传播→ {profile.error_propagation_to}")
            print(f"     控制措施: {controls}")
        print("\n" + "=" * 70)


# ================================================================
# 原理⑤：解耦/非互相影响控制（Decoupling Control）
# "合理设计 Agent 间的信息接口和依赖关系，
#  避免误差在多个 Agent 间级联放大；
#  通过结构化、可验证的中间格式减少误差的'隐性传递'"
# ================================================================

class AgentOutput(BaseModel):
    """
    结构化 Agent 输出格式——解耦接口

    设计目的：
    - 所有 Agent 的输出都必须通过这个结构化格式传递
    - 每个字段都有明确的 schema，可以被下游 Agent 独立校验
    - 避免"自由文本传递"导致的误差隐性传播
    """

    agent_role: str
    content: str                        # 主要输出内容
    confidence: float = 0.8             # 自评置信度 0~1
    structured_data: Optional[Dict] = None  # 结构化数据（如 JSON）
    warnings: List[str] = Field(        # 自检发现的潜在问题
        default_factory=list
    )
    dependencies_used: List[str] = Field(  # 使用了哪些上游输出
        default_factory=list
    )


class DecouplingValidator:
    """
    解耦校验器：检查 Agent 间的信息传递是否规范

    规则：
    1. 每个 Agent 只能读取其声明的 dependency
    2. 每个 Agent 的输出必须符合 AgentOutput schema
    3. 低置信度输出自动触发额外校验
    """

    DEPENDENCY_GRAPH = {
        "director": ["outline", "surprise", "foreshadowing"],
        "protagonist": ["director"],
        "ensemble": ["director"],
        "surprise": ["memory", "foreshadowing_state"],
        "foreshadowing": ["memory", "surprise"],
        "consistency": ["protagonist", "ensemble", "director"],
        "prose": ["protagonist", "ensemble"],
    }

    @classmethod
    def validate_output(cls, output: AgentOutput) -> List[str]:
        """校验输出的结构完整性"""
        issues = []

        if not output.content or len(output.content.strip()) < 10:
            issues.append(
                f"[{output.agent_role}] 输出内容过短或为空"
            )

        if output.confidence < 0.3:
            issues.append(
                f"[{output.agent_role}] 自评置信度极低"
                f"({output.confidence:.2f})，建议重新生成"
            )

        allowed = cls.DEPENDENCY_GRAPH.get(output.agent_role, [])
        for dep in output.dependencies_used:
            if dep not in allowed:
                issues.append(
                    f"[{output.agent_role}] 使用了未声明的"
                    f"依赖'{dep}'，可能导致误差耦合"
                )

        return issues

    @classmethod
    def print_dependency_graph(cls):
        """打印 Agent 依赖关系图"""
        print("\n📊 Agent 依赖关系图（解耦控制）：")
        for agent, deps in cls.DEPENDENCY_GRAPH.items():
            print(f"  {agent:18s} ← {deps}")
