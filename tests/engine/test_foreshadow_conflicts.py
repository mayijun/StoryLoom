"""伏笔回溯补录的一致性校验测试（无需 API Key）。"""

import asyncio

from storyloom.engine.narrative import NarrativeEngine
from storyloom.memory.models import Foreshadowing


def test_foreshadow_retroactive_conflict_blocks(project):
    engine = NarrativeEngine(project=project)
    project.scene_count = 3
    fs = Foreshadowing(
        description="宫廷密令",
        planted_in_scene="scene_1",
        target_revelation="国王早已知道真相",
        visible_to=["不存在的角色"],
    )

    issues = asyncio.run(engine.check_foreshadow_conflicts(project, fs))
    assert any(
        issue["severity"] == "major" and "不存在的角色" in issue["conflict"]
        for issue in issues
    )

    class _StubDirectorCrew:
        def director(self):
            return object()

    async def _fake_kickoff(agent, prompt, timeout_s=60.0):
        return (
            '{"passed": false, "conflicts": ['
            '{"severity": "major", "conflict": "与历史场景记忆冲突",'
            ' "evidence": "scene_1 中该角色尚未出场"}]}'
        )

    engine.crew = _StubDirectorCrew()
    engine._kickoff = _fake_kickoff
    fs.visible_to = []
    issues = asyncio.run(engine.check_foreshadow_conflicts(project, fs))
    assert any(
        issue["severity"] == "major"
        and "历史场景记忆" in issue["conflict"]
        for issue in issues
    )
