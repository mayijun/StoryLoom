"""控制论模块单元测试（无需 API Key）"""

from storyloom.control.hierarchy import ControlDecision, SystemOrchestrator
from storyloom.control.robustness import (
    AgentOutput,
    DecouplingValidator,
    SensitivityAnalyzer,
    SensitivityTier,
)


def test_sensitivity_profiles():
    assert (
        SensitivityAnalyzer.get_profile("director").sensitivity_tier
        == SensitivityTier.CRITICAL
    )
    assert (
        SensitivityAnalyzer.get_profile("ensemble").sensitivity_tier
        == SensitivityTier.LOW
    )
    assert SensitivityAnalyzer.get_profile("surprise").n_samples == 3


def test_orchestrator_decisions():
    orchestrator = SystemOrchestrator(auto_mode=True)

    assert (
        orchestrator.decide_control_strategy("surprise")
        == ControlDecision.MULTI_SAMPLE
    )
    assert (
        orchestrator.decide_control_strategy("foreshadowing")
        == ControlDecision.FEEDBACK_LOOP
    )
    assert (
        orchestrator.decide_control_strategy("ensemble")
        == ControlDecision.PASS
    )


def test_quality_gate():
    orchestrator = SystemOrchestrator(auto_mode=True)

    low = AgentOutput(
        agent_role="director", content="短", confidence=0.2
    )
    high = AgentOutput(
        agent_role="director",
        content="这是一个足够长的场景意图包内容",
        confidence=0.9,
    )

    assert orchestrator.quality_gate("director", low) is False
    assert orchestrator.quality_gate("director", high) is True


def test_decoupling_validator_detects_undeclared_dependency():
    output = AgentOutput(
        agent_role="ensemble",
        content="群演的一句足够长的台词内容",
        dependencies_used=["foreshadowing"],
    )
    issues = DecouplingValidator.validate_output(output)
    assert any("未声明的依赖" in issue for issue in issues)


def test_human_review_auto_mode():
    orchestrator = SystemOrchestrator(auto_mode=True)
    result = orchestrator.human_review_gate("director", "内容")
    assert result["approved"] is True
