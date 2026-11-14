"""旧库可见范围迁移测试：visibility + known_by → visible_to。"""

from storyloom.db import CrewConfigRepository, reset_engines, reset_repositories

LEGACY_MEMORY_DDL = """
CREATE TABLE memory_items (
    id VARCHAR(64) PRIMARY KEY,
    project_id VARCHAR(64),
    tier VARCHAR(32),
    text TEXT,
    summary TEXT DEFAULT '',
    importance FLOAT DEFAULT 0.5,
    pinned BOOLEAN DEFAULT 0,
    scene_index INTEGER DEFAULT 0,
    hits INTEGER DEFAULT 0,
    adoptions INTEGER DEFAULT 0,
    last_hit_scene INTEGER DEFAULT 0,
    tags JSON,
    source VARCHAR(32) DEFAULT 'scene',
    active_foreshadow BOOLEAN DEFAULT 0,
    visibility VARCHAR(32) DEFAULT 'restricted',
    known_by JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

LEGACY_FORESHADOW_DDL = """
CREATE TABLE foreshadowings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id VARCHAR(64),
    foreshadow_id VARCHAR(64),
    description TEXT,
    planted_in_scene VARCHAR(64),
    target_revelation TEXT,
    status VARCHAR(32) DEFAULT 'planted',
    reinforcement_count INTEGER DEFAULT 0,
    max_dormant_scenes INTEGER DEFAULT 5,
    scenes_since_last_mention INTEGER DEFAULT 0,
    linked_characters JSON,
    linked_surprise_ids JSON,
    visibility VARCHAR(32) DEFAULT 'restricted',
    known_by JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
)
"""

LEGACY_CONFIG_DDL = """
CREATE TABLE memory_configs (
    project_id VARCHAR(64) PRIMARY KEY,
    payload JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
)
"""


def _seed_legacy_database(repo: CrewConfigRepository) -> None:
    with repo.engine.begin() as conn:
        conn.exec_driver_sql(LEGACY_MEMORY_DDL)
        conn.exec_driver_sql(
            "INSERT INTO memory_items "
            "(id, project_id, tier, text, visibility, known_by) VALUES "
            "('p_old::public', 'p_old', 'long_term', '公开事实', 'public', '[]'),"
            "('p_old::private', 'p_old', 'long_term', '私密事实', "
            "'private:张三', '[]'),"
            "('p_old::restricted', 'p_old', 'long_term', '受限事实', "
            "'restricted', '[\"李四\", \"张三\", \"gm\"]'),"
            "('p_old::canon', 'p_old', 'canon', '旧正史', 'restricted', '[]')"
        )
        conn.exec_driver_sql(LEGACY_FORESHADOW_DDL)
        conn.exec_driver_sql(
            "INSERT INTO foreshadowings "
            "(project_id, foreshadow_id, description, planted_in_scene, "
            "target_revelation, visibility, known_by) VALUES "
            "('p_old', 'fs_known', '旧航海图', 'scene_1', '指向密道', "
            "'restricted', '[\"林夏\"]'),"
            "('p_old', 'fs_secret', '无名伏笔', 'scene_2', '无人知晓', "
            "NULL, NULL)"
        )
        conn.exec_driver_sql(LEGACY_CONFIG_DDL)
        conn.exec_driver_sql(
            "INSERT INTO memory_configs (project_id, payload) VALUES "
            "('p_old', '{\"canon\": {\"max_items\": 7}, "
            "\"tiers\": [{\"name\": \"short_term\", \"max_items\": 2, "
            "\"compress_batch\": 1, \"compress_into\": \"canon\"}]}')"
        )


def test_legacy_visibility_backfills_visible_to(tmp_path):
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    repo = CrewConfigRepository(url)
    _seed_legacy_database(repo)

    repo.create_all()

    items = {
        row["id"].split("::", 1)[1]: row
        for row in repo.list_memory_items("p_old")
    }
    assert items["public"]["visible_to"] == ["all"]
    assert items["private"]["visible_to"] == ["张三"]
    assert items["restricted"]["visible_to"] == ["张三", "李四"]
    assert items["canon"]["tier"] == "key_events"
    assert items["canon"]["visible_to"] == []

    known = repo.get_foreshadowing("fs_known", "p_old")
    secret = repo.get_foreshadowing("fs_secret", "p_old")
    assert known["visible_to"] == ["林夏"]
    assert secret["visible_to"] == []

    config = repo.load_memory_config("p_old")
    assert config["key_events"]["max_items"] == 7
    assert config["tiers"][0]["compress_into"] == "key_events"

    # 重复启动不得重复回填或覆盖已迁移的值
    repo.create_all()
    again = {
        row["id"].split("::", 1)[1]: row
        for row in repo.list_memory_items("p_old")
    }
    assert again["private"]["visible_to"] == ["张三"]
    assert again["restricted"]["visible_to"] == ["张三", "李四"]

    reset_repositories()
    reset_engines()
