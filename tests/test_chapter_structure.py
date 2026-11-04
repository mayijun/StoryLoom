"""章节结构测试（无需 API Key）

覆盖：
- chapters 表 CRUD + 自动 position + 外键约束
- 场景归属章节（assign_scene_to_chapter）+ 按章节查询
- 删除章节时场景 chapter_id 被 SET NULL（不丢场景）
- 旧库迁移：scenes 表缺 chapter FK 时自动重建
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from storyloom.db import (
    CrewConfigRepository,
    reset_engines,
    reset_repositories,
)


@pytest.fixture
def repo(tmp_path):
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'chapter.db'}"
    r = CrewConfigRepository(url)
    r.create_all()
    r.create_project("novel_c", "章节测试", "wuxia")
    yield r
    reset_repositories()
    reset_engines()


# ============================================================
# 章节 CRUD
# ============================================================

def test_create_chapter_persists(repo):
    ch = repo.create_chapter(
        chapter_id="ch_1", project_id="novel_c", title="第一章", outline="开场"
    )
    assert ch["title"] == "第一章"
    assert ch["position"] == 0  # 首个章节 position=0
    assert repo.get_chapter("ch_1")["outline"] == "开场"


def test_auto_position_increments(repo):
    repo.create_chapter("ch_a", "novel_c", "A")
    repo.create_chapter("ch_b", "novel_c", "B")
    repo.create_chapter("ch_c", "novel_c", "C")
    positions = [c["position"] for c in repo.list_chapters("novel_c")]
    assert positions == [0, 1, 2]


def test_explicit_position_allowed(repo):
    repo.create_chapter("ch_x", "novel_c", "X", position=10)
    repo.create_chapter("ch_y", "novel_c", "Y")  # 自动取 max+1
    assert repo.get_chapter("ch_y")["position"] == 11


def test_update_chapter(repo):
    repo.create_chapter("ch_1", "novel_c", "旧标题", status="draft")
    updated = repo.update_chapter("ch_1", title="新标题", status="locked")
    assert updated["title"] == "新标题"
    assert updated["status"] == "locked"


def test_delete_chapter(repo):
    repo.create_chapter("ch_1", "novel_c", "t")
    assert repo.delete_chapter("ch_1") is True
    assert repo.get_chapter("ch_1") is None


def test_chapter_foreign_key_rejects_orphan(repo):
    with repo.engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO chapters (chapter_id, project_id, title, position)"
                " VALUES ('ch_x', 'ghost', 't', 1)"
            )


def test_delete_project_cascades_chapters(repo):
    repo.create_project("novel_d", "d", "scifi")
    repo.create_chapter("ch_d1", "novel_d", "d1")
    repo.create_chapter("ch_c1", "novel_c", "c1")
    repo.delete_project("novel_d")
    assert repo.get_chapter("ch_d1") is None
    assert repo.get_chapter("ch_c1") is not None


# ============================================================
# 场景归属章节
# ============================================================

def test_assign_scene_to_chapter(repo):
    repo.create_chapter("ch_1", "novel_c", "第一章")
    repo.create_scene("scene_1", "novel_c", brief="b", prose="p")

    updated = repo.assign_scene_to_chapter("scene_1", "ch_1")
    assert updated["chapter_id"] == "ch_1"

    # 按章节查询
    scenes = repo.list_scenes_by_chapter("novel_c", "ch_1")
    assert len(scenes) == 1 and scenes[0]["scene_id"] == "scene_1"


def test_assign_scene_to_nonexistent_chapter_raises(repo):
    repo.create_scene("scene_1", "novel_c", brief="b", prose="p")
    with pytest.raises(ValueError):
        repo.assign_scene_to_chapter("scene_1", "ch_ghost")


def test_unassign_scene(repo):
    repo.create_chapter("ch_1", "novel_c", "第一章")
    repo.create_scene("scene_1", "novel_c", brief="b", prose="p")
    repo.assign_scene_to_chapter("scene_1", "ch_1")
    # 解除归属
    repo.assign_scene_to_chapter("scene_1", None)
    assert repo.get_scene("scene_1")["chapter_id"] is None


def test_delete_chapter_sets_scene_chapter_null(repo):
    """ON DELETE SET NULL：删章节不丢场景，只解除归属"""
    repo.create_chapter("ch_1", "novel_c", "第一章")
    repo.create_scene("scene_1", "novel_c", brief="b", prose="p")
    repo.assign_scene_to_chapter("scene_1", "ch_1")

    repo.delete_chapter("ch_1")

    # 场景仍在，但 chapter_id 被置 NULL
    scene = repo.get_scene("scene_1")
    assert scene is not None
    assert scene["chapter_id"] is None
    # 出现在"未归属"列表
    unassigned = repo.list_scenes_by_chapter("novel_c", None)
    assert any(s["scene_id"] == "scene_1" for s in unassigned)


def test_list_unassigned_scenes(repo):
    repo.create_chapter("ch_1", "novel_c", "第一章")
    repo.create_scene("scene_assigned", "novel_c", brief="b", prose="p")
    repo.create_scene("scene_free", "novel_c", brief="b", prose="p")
    repo.assign_scene_to_chapter("scene_assigned", "ch_1")

    free = repo.list_scenes_by_chapter("novel_c", None)
    assigned = repo.list_scenes_by_chapter("novel_c", "ch_1")
    assert [s["scene_id"] for s in free] == ["scene_free"]
    assert [s["scene_id"] for s in assigned] == ["scene_assigned"]


# ============================================================
# 旧库迁移：scenes 缺 chapter FK
# ============================================================

def test_migrate_scenes_without_chapter_fk(tmp_path):
    """模拟 #1 时期的库：scenes 表存在但没有指向 chapters 的外键。
    重启后应自动重建 scenes 表（带上 chapter FK），且场景数据保留。"""
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'legacy.db'}"

    # 第一步：手工建一个"旧版"库（scenes 无 chapter FK，无 chapters 表）
    r1 = CrewConfigRepository(url)
    r1.create_all()
    r1.create_project("novel_old", "旧库", "wuxia")
    # 直接用原生 SQL 建一个不带 chapter FK 的 scenes 表并插数据
    with r1.engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS scenes")
        conn.exec_driver_sql(
            "CREATE TABLE scenes ("
            "scene_id VARCHAR(64) PRIMARY KEY, "
            "project_id VARCHAR(64), "
            "chapter_id VARCHAR(64), "
            "brief TEXT, present_characters TEXT, prose TEXT, "
            "quality_score FLOAT, duration_ms INTEGER, model_usage TEXT, "
            "created_at DATETIME)"
        )
        conn.exec_driver_sql(
            "INSERT INTO scenes (scene_id, project_id, chapter_id, brief, prose)"
            " VALUES ('s_old', 'novel_old', NULL, '旧场景', '旧正文')"
        )

    # 第二步：模拟重启，新建 repository 实例
    reset_repositories()
    r2 = CrewConfigRepository(url)
    r2.create_all()

    # chapters 表已建
    inspector = sa.inspect(r2.engine)
    assert inspector.has_table("chapters")

    # scenes 已有 chapter FK
    scene_fks = inspector.get_foreign_keys("scenes")
    has_chapter_fk = any(
        "chapter_id" in fk["constrained_columns"]
        and "chapters" in fk.get("referred_table", "")
        for fk in scene_fks
    )
    assert has_chapter_fk, "迁移后 scenes 应有指向 chapters 的外键"

    # 旧场景数据保留
    scene = r2.get_scene("s_old")
    assert scene is not None
    assert scene["prose"] == "旧正文"

    reset_repositories()
    reset_engines()
