"""Flow 辅助逻辑单元测试（无需 API Key）"""

import pytest

from storyloom.models import (
    ForeshadowStatus,
    Foreshadowing,
    NovelProject,
)
from storyloom.flows.scene_flow import (
    advance_scene_counters,
    apply_foreshadow_ops,
    parse_json_block,
)


def make_project() -> NovelProject:
    return NovelProject(
        project_id="test",
        title="测试",
        style="克制",
        characters=[],
        locations=[],
        foreshadowings=[
            Foreshadowing(
                foreshadow_id="fs_map",
                description="旧航海图",
                planted_in_scene="scene_0",
                target_revelation="逃亡路线",
                max_dormant_scenes=2,
            )
        ],
    )


def test_parse_json_block_extracts_object():
    raw = '说明文字\n{"passed": true, "conflicts": []}\n结束'
    assert parse_json_block(raw)["passed"] is True


def test_parse_json_block_raises_without_json():
    with pytest.raises(ValueError):
        parse_json_block("没有任何 JSON")


def test_apply_reinforce_resets_dormancy():
    project = make_project()
    fs = project.foreshadowings[0]
    fs.scenes_since_last_mention = 3

    apply_foreshadow_ops(
        project,
        [{"action": "reinforce", "foreshadow_id": "fs_map"}],
    )

    assert fs.reinforcement_count == 1
    assert fs.scenes_since_last_mention == 0
    assert fs.status == ForeshadowStatus.REINFORCED


def test_apply_plant_adds_foreshadow():
    project = make_project()
    apply_foreshadow_ops(
        project,
        [{
            "action": "plant",
            "new_foreshadow": {
                "description": "阿泽手腕的纹身",
                "target_revelation": "他与姐姐有关",
                "linked_characters": ["阿泽"],
                "max_dormant_scenes": 3,
            },
        }],
    )
    assert len(project.foreshadowings) == 2
    assert project.foreshadowings[-1].status == ForeshadowStatus.PLANTED


def test_apply_resolve_closes_foreshadow():
    project = make_project()
    apply_foreshadow_ops(
        project,
        [{"action": "resolve", "foreshadow_id": "fs_map"}],
    )
    assert (
        project.foreshadowings[0].status == ForeshadowStatus.RESOLVED
    )


def test_advance_scene_counters_increments():
    project = make_project()
    advance_scene_counters(project)

    assert project.scene_count == 1
    assert project.foreshadowings[0].scenes_since_last_mention == 1
