"""资产层单元测试（无需 API Key）"""

from storyloom.models import (
    CharacterAsset,
    ForeshadowStatus,
    Foreshadowing,
    LocationAsset,
    NovelProject,
    SurpriseType,
)


def make_project() -> NovelProject:
    return NovelProject(
        project_id="test",
        title="测试小说",
        style="克制",
        characters=[
            CharacterAsset(
                name="林夏",
                importance_tier="primary",
                persona="冷静",
                motivation="寻找姐姐",
            )
        ],
        locations=[LocationAsset(name="旅店", description="昏暗")],
    )


def test_character_importance_tier():
    char = CharacterAsset(
        name="阿泽",
        importance_tier="secondary",
        persona="话多",
        motivation="套情报",
    )
    assert char.importance_tier == "secondary"
    assert char.secrets == ""


def test_foreshadowing_defaults():
    f = Foreshadowing(
        description="旧航海图",
        planted_in_scene="scene_0",
        target_revelation="逃亡路线",
    )
    assert f.status == ForeshadowStatus.PLANTED
    assert f.reinforcement_count == 0
    assert f.scenes_since_last_mention == 0
    assert f.foreshadow_id.startswith("fs_")


def test_project_lookup_and_defaults():
    project = make_project()
    assert project.get_character("林夏") is not None
    assert project.get_character("不存在") is None
    assert project.scene_count == 0
    assert project.surprise_cooldown == 3
    assert project.foreshadowings == []


def test_surprise_type_values():
    assert SurpriseType.CHARACTER.value == "character"
    assert {t.value for t in SurpriseType} == {
        "character",
        "information",
        "environment",
        "relationship",
        "temporal",
    }
