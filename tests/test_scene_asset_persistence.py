"""场景与资产落库测试（无需 API Key）

覆盖：
- scenes 表 CRUD + 外键约束 + 项目删除级联
- characters / locations / foreshadowings 表 CRUD + 外键 + 级联
- 引擎重启后资产从 DB 重建（_build_project 加载）
"""

import pytest
from sqlalchemy.exc import IntegrityError

from storyloom.db import (
    DEFAULT_PROJECT_ID,
    CrewConfigRepository,
    get_engine,
    reset_engines,
    reset_repositories,
)


@pytest.fixture
def repo(tmp_path):
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'asset.db'}"
    r = CrewConfigRepository(url)
    r.create_all()
    r.create_project("novel_x", "测试小说", "wuxia")
    yield r
    reset_repositories()
    reset_engines()


# ============================================================
# 场景（SceneRow）
# ============================================================

def test_create_scene_persists(repo):
    scene = repo.create_scene(
        scene_id="scene_1",
        project_id="novel_x",
        brief="主角登场",
        present_characters=["主角"],
        prose="一段正文",
        quality_score=0.85,
        duration_ms=1234,
        model_usage={"director": "deepseek"},
    )
    assert scene["scene_id"] == "scene_1"
    assert scene["prose"] == "一段正文"
    assert scene["present_characters"] == ["主角"]
    assert scene["quality_score"] == 0.85

    # 能从 DB 查回
    got = repo.get_scene("scene_1")
    assert got is not None
    assert got["prose"] == "一段正文"


def test_list_scenes_isolated_by_project(repo):
    repo.create_project("novel_y", "另一本", "scifi")
    repo.create_scene("scene_a", "novel_x", brief="x", prose="px")
    repo.create_scene("scene_b", "novel_y", brief="y", prose="py")

    x_scenes = repo.list_scenes("novel_x")
    y_scenes = repo.list_scenes("novel_y")
    assert len(x_scenes) == 1 and x_scenes[0]["prose"] == "px"
    assert len(y_scenes) == 1 and y_scenes[0]["prose"] == "py"


def test_update_scene_prose(repo):
    repo.create_scene("scene_1", "novel_x", brief="b", prose="旧正文")
    updated = repo.update_scene("scene_1", prose="新正文", quality_score=0.9)
    assert updated["prose"] == "新正文"
    assert updated["quality_score"] == 0.9
    # brief 未传则保留
    assert updated["brief"] == "b"


def test_update_nonexistent_scene_returns_none(repo):
    assert repo.update_scene("nope", prose="x") is None


def test_delete_scene(repo):
    repo.create_scene("scene_1", "novel_x", brief="b", prose="p")
    assert repo.delete_scene("scene_1") is True
    assert repo.get_scene("scene_1") is None
    assert repo.delete_scene("scene_1") is False


def test_scene_foreign_key_rejects_orphan(repo):
    """scene.project_id 必须指向已存在的 projects 行。
    注意：repo.create_scene 会先 ensure_project 自动建占位行，
    因此用原生 SQL 直插绕过该逻辑，验证底层外键约束。"""
    with repo.engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO scenes (scene_id, project_id, brief, prose)"
                " VALUES ('s1', 'ghost_proj', 'b', 'p')"
            )


def test_delete_project_cascades_scenes(repo):
    repo.create_scene("scene_1", "novel_x", brief="b", prose="p")
    repo.create_project("novel_y", "另一本", "scifi")
    repo.create_scene("scene_y", "novel_y", brief="b", prose="p")

    assert repo.delete_project("novel_x") is True
    # novel_x 的场景被级联删除
    assert repo.get_scene("scene_1") is None
    # novel_y 的场景不受影响
    assert repo.get_scene("scene_y") is not None


# ============================================================
# 角色（CharacterRow）
# ============================================================

def test_upsert_character_persists(repo):
    c = repo.upsert_character(
        "novel_x", "郭靖", "primary", "忠厚", "守襄阳", "隐藏: 是郭啸天之子"
    )
    assert c["name"] == "郭靖"
    assert c["importance_tier"] == "primary"

    chars = repo.list_characters("novel_x")
    assert len(chars) == 1
    assert chars[0]["persona"] == "忠厚"


def test_upsert_character_update_existing(repo):
    repo.upsert_character("novel_x", "郭靖", "primary", "忠厚", "守襄阳")
    # 重名 → 更新而非重复插入
    repo.upsert_character("novel_x", "郭靖", "secondary", "机灵", "玩")
    chars = repo.list_characters("novel_x")
    assert len(chars) == 1
    assert chars[0]["importance_tier"] == "secondary"
    assert chars[0]["persona"] == "机灵"


def test_delete_character(repo):
    repo.upsert_character("novel_x", "郭靖", "primary", "p", "m")
    assert repo.delete_character_asset("郭靖", "novel_x") is True
    assert repo.get_character_asset("郭靖", "novel_x") is None


def test_character_foreign_key_rejects_orphan(repo):
    """同 scenes，用原生 SQL 绕过 ensure_project 验证外键。"""
    with repo.engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO characters (project_id, name, importance_tier,"
                " persona, motivation) VALUES ('ghost', 'x', 'primary', 'p', 'm')"
            )


def test_characters_isolated_by_project(repo):
    repo.create_project("novel_y", "y", "scifi")
    repo.upsert_character("novel_x", "郭靖", "primary", "p", "m")
    repo.upsert_character("novel_y", "Spock", "primary", "p", "m")
    assert len(repo.list_characters("novel_x")) == 1
    assert len(repo.list_characters("novel_y")) == 1


# ============================================================
# 地点（LocationRow）
# ============================================================

def test_upsert_location_persists(repo):
    loc = repo.upsert_location("novel_x", "襄阳城", "南宋军事重镇")
    assert loc["name"] == "襄阳城"
    assert repo.list_locations("novel_x")[0]["description"] == "南宋军事重镇"


def test_delete_location_cascades_with_project(repo):
    repo.upsert_location("novel_x", "襄阳", "城")
    repo.delete_project("novel_x")
    # 项目删除级联清理地点
    assert repo.list_locations("novel_x") == []


# ============================================================
# 伏笔（ForeshadowRow）
# ============================================================

def test_upsert_foreshadowing_persists(repo):
    fs = repo.upsert_foreshadowing(
        "novel_x",
        foreshadow_id="fs_001",
        description="墙上的航海图",
        planted_in_scene="scene_1",
        target_revelation="父亲的下落",
        status="planted",
        linked_characters=["郭靖"],
    )
    assert fs["foreshadow_id"] == "fs_001"
    assert fs["linked_characters"] == ["郭靖"]

    got = repo.get_foreshadowing("fs_001", "novel_x")
    assert got["status"] == "planted"


def test_foreshadowing_cascades_with_project(repo):
    repo.upsert_foreshadowing(
        "novel_x", "fs_1", "d", "s1", "r", status="planted"
    )
    repo.delete_project("novel_x")
    assert repo.list_foreshadowings("novel_x") == []


# ============================================================
# 引擎重启：资产从 DB 重建
# ============================================================

def test_engine_rebuilds_assets_from_db(tmp_path):
    """模拟服务重启：新建 repository 实例后，资产仍可从 DB 读出。"""
    from storyloom.api.engine import StoryEngine, engine as global_engine
    # 避免污染全局 engine：直接测 repository 的 _build_project 等价路径
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'rebuild.db'}"

    r1 = CrewConfigRepository(url)
    r1.create_all()
    r1.create_project("novel_rebuild", "重启测试", "wuxia")
    r1.upsert_character("novel_rebuild", "黄蓉", "primary", "聪慧", "帮靖哥哥")
    r1.upsert_location("novel_rebuild", "桃花岛", "黄药师居所")
    r1.upsert_foreshadowing(
        "novel_rebuild", "fs_a", "九阴真经", "scene_1", "真经下落",
        status="planted",
    )
    r1.create_scene("scene_1", "novel_rebuild", brief="b", prose="正文一")

    # 模拟重启：全新 repository 实例
    reset_repositories()
    r2 = CrewConfigRepository(url)

    assert len(r2.list_characters("novel_rebuild")) == 1
    assert r2.get_character_asset("黄蓉", "novel_rebuild")["persona"] == "聪慧"
    assert len(r2.list_locations("novel_rebuild")) == 1
    assert len(r2.list_foreshadowings("novel_rebuild")) == 1
    assert r2.get_scene("scene_1")["prose"] == "正文一"

    reset_repositories()
    reset_engines()


