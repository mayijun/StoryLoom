"""项目落库与外键关联的单元测试（无需 API Key）

覆盖：
- 项目 CRUD 落库
- 创建项目自动播种 agent/task
- 外键约束（ON DELETE CASCADE 生效 / 拒绝悬挂 project_id）
- demo 内置项目保护
- 旧库迁移（有 project_id 但无外键 → 自动补外键）
- create_project 的 SQLite 写锁回归（曾经在 session 内嵌套 seed 导致 database is locked）
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from storyloom.db import (
    DEFAULT_PROJECT_ID,
    CrewConfigRepository,
    get_engine,
    reset_engines,
    reset_repositories,
)
from storyloom.db.models import AgentConfigRow, TaskConfigRow


@pytest.fixture
def repo(tmp_path):
    """每个测试独立的临时 SQLite 文件，避免相互污染"""
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'config.db'}"
    yield CrewConfigRepository(url)
    reset_repositories()
    reset_engines()


# ---------------- 项目 CRUD ----------------


def test_create_project_persists_to_db(repo):
    """创建项目后，list_projects / get_project 能从 DB 读到"""
    repo.create_project("novel_a", "星际迷航", "sci-fi", "外键验证")

    projects = repo.list_projects()
    assert any(p["project_id"] == "novel_a" for p in projects)

    proj = repo.get_project("novel_a")
    assert proj is not None
    assert proj["title"] == "星际迷航"
    assert proj["style"] == "sci-fi"
    assert proj["description"] == "外键验证"
    assert proj["scene_count"] == 0


def test_create_project_auto_seeds_agents_and_tasks(repo):
    """新项目自动播种默认的 8 个 agent + 6 个 task"""
    repo.create_project("novel_b", "武侠江湖", "wuxia")

    agents = repo.list_agents(project_id="novel_b")
    tasks = repo.list_tasks(project_id="novel_b")
    assert len(agents) == 8
    assert len(tasks) == 6
    # 归属正确的 project_id
    assert all(a["project_id"] == "novel_b" for a in agents)
    assert all(t["project_id"] == "novel_b" for t in tasks)


def test_create_project_duplicate_raises(repo):
    """重复创建同一个 project_id 应抛 ValueError"""
    repo.create_project("novel_dup", "第一次", "sci-fi")
    with pytest.raises(ValueError, match="已存在"):
        repo.create_project("novel_dup", "第二次", "wuxia")


def test_create_project_no_sqlite_lock(repo):
    """回归：create_project 曾因在 session 块内嵌套调用 seed_from_yaml
    导致 SQLite database is locked。修复后应能正常完成。"""
    # 不抛异常即通过
    repo.create_project("novel_lock", "锁测试", "sci-fi")
    assert repo.get_project("novel_lock") is not None
    assert len(repo.list_agents(project_id="novel_lock")) == 8


def test_update_project_stats(repo):
    """生成场景后统计字段写回 DB"""
    repo.create_project("novel_stats", "统计测试", "sci-fi")
    repo.update_project_stats(
        "novel_stats", scene_count=3, character_count=5, foreshadowing_count=2
    )
    proj = repo.get_project("novel_stats")
    assert proj["scene_count"] == 3
    assert proj["character_count"] == 5
    assert proj["foreshadowing_count"] == 2


def test_update_project_stats_missing_returns_none(repo):
    """更新不存在项目的统计返回 None，不抛异常"""
    repo.create_all()  # 表已建但项目不存在
    result = repo.update_project_stats("ghost", scene_count=1)
    assert result is None


# ---------------- 外键约束 ----------------


def test_foreign_key_rejects_orphan_agent_insert(repo):
    """直接向 agent_configs 插入不存在的 project_id 应被外键拒绝"""
    repo.ensure_seeded()  # 建表
    with pytest.raises(IntegrityError):
        with repo.session() as session:
            session.add(
                AgentConfigRow(
                    project_id="nonexistent_project",
                    crew="scene_crew",
                    key="rogue",
                    role="r",
                    goal="g",
                    backstory="b",
                )
            )
            session.flush()


def test_foreign_key_rejects_orphan_task_insert(repo):
    """直接向 task_configs 插入不存在的 project_id 应被外键拒绝"""
    repo.ensure_seeded()
    with pytest.raises(IntegrityError):
        with repo.session() as session:
            session.add(
                TaskConfigRow(
                    project_id="nonexistent_project",
                    crew="scene_crew",
                    key="rogue_task",
                    description="d",
                    expected_output="o",
                )
            )
            session.flush()


def test_delete_project_cascades_agents_and_tasks(repo):
    """删除项目时其所有 agent/task 配置级联清理（用底层 SQL 验证，绕开 list_agents 的自动 seed）"""
    repo.create_project("novel_cascade", "级联测试", "sci-fi")
    assert len(repo.list_agents(project_id="novel_cascade")) == 8
    assert len(repo.list_tasks(project_id="novel_cascade")) == 6

    result = repo.delete_project("novel_cascade")
    assert result is True

    # 用原生 SQL 验证：绕开 list_agents / get_project 的 ensure_seeded 自愈行为
    with repo.engine.connect() as conn:
        proj_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM projects WHERE project_id = 'novel_cascade'"
        ).scalar()
        agent_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM agent_configs WHERE project_id = 'novel_cascade'"
        ).scalar()
        task_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM task_configs WHERE project_id = 'novel_cascade'"
        ).scalar()
    assert proj_count == 0
    assert agent_count == 0  # 外键 ON DELETE CASCADE 生效
    assert task_count == 0


def test_delete_project_isolates_other_projects(repo):
    """删除项目 A 不影响项目 B 的配置"""
    repo.create_project("proj_keep", "保留", "sci-fi")
    repo.create_project("proj_drop", "删除", "wuxia")

    repo.delete_project("proj_drop")

    assert len(repo.list_agents(project_id="proj_keep")) == 8
    assert len(repo.list_tasks(project_id="proj_keep")) == 6
    assert repo.get_project("proj_keep") is not None


def test_delete_demo_project_forbidden(repo):
    """demo 内置项目禁止删除"""
    repo.ensure_seeded()
    with pytest.raises(ValueError, match="demo"):
        repo.delete_project(DEFAULT_PROJECT_ID)
    # demo 还在
    assert repo.get_project(DEFAULT_PROJECT_ID) is not None


def test_delete_nonexistent_project_returns_false(repo):
    """删除不存在的项目返回 False，不抛异常"""
    repo.ensure_seeded()
    assert repo.delete_project("no_such_project") is False


# ---------------- 旧库迁移 ----------------


def test_legacy_db_with_project_id_but_no_fk_migrates(tmp_path):
    """
    旧库：agent_configs 有 project_id 列但没有指向 projects 的外键约束。
    迁移后：表结构带上外键，旧数据保留，projects 表自动补全对应行。
    """
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'legacy_no_fk.db'}"
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        # 建一个"过渡形态"的旧表：有 project_id 但无外键
        conn.exec_driver_sql(
            """
            CREATE TABLE agent_configs (
                id INTEGER PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL,
                crew VARCHAR(64) NOT NULL,
                key VARCHAR(64) NOT NULL,
                role TEXT NOT NULL,
                goal TEXT NOT NULL,
                backstory TEXT NOT NULL,
                allow_delegation BOOLEAN,
                verbose BOOLEAN,
                max_iter INTEGER,
                settings JSON,
                enabled BOOLEAN,
                position INTEGER,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        conn.exec_driver_sql(
            "INSERT INTO agent_configs (project_id, crew, key, role, goal,"
            " backstory, settings, enabled, position) VALUES"
            " ('old_novel', 'scene_crew', 'director', '导演', '目标', '背景',"
            " '{}', 1, 0)"
        )
    engine.dispose()

    repo = CrewConfigRepository(url)
    repo.ensure_seeded()

    # 旧数据保留
    director = repo.get_agent("director", project_id="old_novel")
    assert director is not None
    assert director["backstory"] == "背景"

    # projects 表里自动补全了 old_novel（占位 title）
    proj = repo.get_project("old_novel")
    assert proj is not None
    assert proj["project_id"] == "old_novel"

    # 新表结构上有指向 projects 的外键
    inspector = sa.inspect(repo.engine)
    fks = inspector.get_foreign_keys("agent_configs")
    assert any(
        "project_id" in fk["constrained_columns"]
        and fk.get("referred_table") == "projects"
        for fk in fks
    ), "迁移后 agent_configs 应有指向 projects 的外键"

    reset_repositories()
    reset_engines()


def test_migration_preserves_multiple_projects(tmp_path):
    """旧库里有多个 project_id 的数据，迁移后全部保留且互不串扰"""
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'legacy_multi.db'}"
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE agent_configs (
                id INTEGER PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL,
                crew VARCHAR(64) NOT NULL,
                key VARCHAR(64) NOT NULL,
                role TEXT NOT NULL,
                goal TEXT NOT NULL,
                backstory TEXT NOT NULL,
                allow_delegation BOOLEAN,
                verbose BOOLEAN,
                max_iter INTEGER,
                settings JSON,
                enabled BOOLEAN,
                position INTEGER,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        for pid in ("alpha", "beta", "gamma"):
            conn.exec_driver_sql(
                f"INSERT INTO agent_configs (project_id, crew, key, role, goal,"
                f" backstory, settings, enabled, position) VALUES"
                f" ('{pid}', 'scene_crew', 'director', '导演', '目标',"
                f" '背景_{pid}', '{{}}', 1, 0)"
            )
    engine.dispose()

    repo = CrewConfigRepository(url)
    repo.ensure_seeded()

    # 三个项目都在 projects 表里
    for pid in ("alpha", "beta", "gamma"):
        assert repo.project_exists(pid), f"projects 表缺少 {pid}"
        director = repo.get_agent("director", project_id=pid)
        assert director is not None
        assert director["backstory"] == f"背景_{pid}"

    reset_repositories()
    reset_engines()


_LEGACY_AGENT_DDL_NO_PID = """
    CREATE TABLE agent_configs (
        id INTEGER PRIMARY KEY,
        crew VARCHAR(64) NOT NULL,
        key VARCHAR(64) NOT NULL,
        role TEXT NOT NULL,
        goal TEXT NOT NULL,
        backstory TEXT NOT NULL,
        allow_delegation BOOLEAN,
        verbose BOOLEAN,
        max_iter INTEGER,
        settings JSON,
        enabled BOOLEAN,
        position INTEGER,
        created_at DATETIME,
        updated_at DATETIME
    )
"""

_LEGACY_TASK_DDL_NO_PID = """
    CREATE TABLE task_configs (
        id INTEGER PRIMARY KEY,
        crew VARCHAR(64) NOT NULL,
        key VARCHAR(64) NOT NULL,
        description TEXT NOT NULL,
        expected_output TEXT NOT NULL,
        agent_key VARCHAR(64),
        context_keys JSON,
        enabled BOOLEAN,
        position INTEGER,
        created_at DATETIME,
        updated_at DATETIME
    )
"""


def test_legacy_db_without_project_id_column_migrates_to_demo(tmp_path):
    """最老形态旧库：agent/task 连 project_id 列都没有。
    迁移后：数据全部归入 demo、projects 表补 demo 行、外键就位，
    且 create_all 末尾的 seed 只补缺失条目、不覆盖 legacy 自定义内容。"""
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'legacy_no_pid.db'}"
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(_LEGACY_AGENT_DDL_NO_PID)
        conn.exec_driver_sql(_LEGACY_TASK_DDL_NO_PID)
        conn.exec_driver_sql(
            "INSERT INTO agent_configs (crew, key, role, goal, backstory,"
            " settings, enabled, position) VALUES"
            " ('scene_crew', 'director', '老导演', '旧目标', '旧背景故事',"
            " '{}', 1, 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO task_configs (crew, key, description, expected_output,"
            " agent_key, context_keys, enabled, position) VALUES"
            " ('scene_crew', 'director_plan', '旧任务描述', '旧产出',"
            " 'director', '[]', 1, 0)"
        )
    engine.dispose()

    repo = CrewConfigRepository(url)
    repo.create_all()  # 直接调迁移入口

    # 旧数据归入 demo 且内容完整保留
    director = repo.get_agent("director", project_id=DEFAULT_PROJECT_ID)
    assert director is not None
    assert director["backstory"] == "旧背景故事"
    assert director["role"] == "老导演"

    task = repo.get_task("director_plan", project_id=DEFAULT_PROJECT_ID)
    assert task is not None
    assert task["description"] == "旧任务描述"

    # demo 行自动补进 projects 表
    assert repo.project_exists(DEFAULT_PROJECT_ID)

    # 外键就位（agent / task 两张表）
    inspector = sa.inspect(repo.engine)
    for table in ("agent_configs", "task_configs"):
        fks = inspector.get_foreign_keys(table)
        assert any(
            "project_id" in fk["constrained_columns"]
            and fk.get("referred_table") == "projects"
            for fk in fks
        ), f"迁移后 {table} 应有指向 projects 的外键"

    # create_all 末尾的 seed_from_yaml 补齐缺失条目但不覆盖 legacy：
    # demo 共 8 个 agent（1 个 legacy director + 7 个 YAML 补种），
    # director 的自定义 backstory 原样保留
    agents = repo.list_agents(project_id=DEFAULT_PROJECT_ID)
    assert len(agents) == 8
    by_key = {a["key"]: a for a in agents}
    assert by_key["director"]["backstory"] == "旧背景故事"
    assert by_key["director"]["role"] == "老导演"

    # created_at/updated_at 被跳过，由 server_default 重新填充（记录序列化不含时间戳，查底层）
    with repo.engine.connect() as conn:
        ts = conn.exec_driver_sql(
            "SELECT created_at, updated_at FROM agent_configs"
            " WHERE project_id='demo' AND key='director'"
        ).one()
    assert ts[0] is not None and ts[1] is not None

    reset_repositories()
    reset_engines()


def test_fresh_db_creates_tables_without_migration(tmp_path):
    """全新空库：create_all 只建表不迁移、不自动 seed；
    ensure_seeded 负责补 demo 行和 YAML 种子。"""
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'fresh.db'}"

    repo = CrewConfigRepository(url)
    repo.create_all()

    inspector = sa.inspect(repo.engine)
    for table in ("projects", "agent_configs", "task_configs"):
        assert inspector.has_table(table), f"缺表 {table}"

    # create_all 本身不 seed：空库时 legacy=None，不触发 seed_from_yaml
    with repo.engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM agent_configs").scalar() == 0
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM projects").scalar() == 0

    # ensure_seeded 才补 demo
    repo.ensure_seeded()
    assert repo.project_exists(DEFAULT_PROJECT_ID)
    assert len(repo.list_agents(project_id=DEFAULT_PROJECT_ID)) == 8
    assert len(repo.list_tasks(project_id=DEFAULT_PROJECT_ID)) == 6

    reset_repositories()
    reset_engines()


def test_reopening_migrated_db_is_idempotent(tmp_path):
    """已迁移的库再次打开（模拟服务重启）：create_all 幂等——
    不重复迁移、不丢数据、不重复播种 demo。"""
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'legacy_reopen.db'}"

    # 第一次：迁移 + seed
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE agent_configs (
                id INTEGER PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL,
                crew VARCHAR(64) NOT NULL,
                key VARCHAR(64) NOT NULL,
                role TEXT NOT NULL,
                goal TEXT NOT NULL,
                backstory TEXT NOT NULL,
                allow_delegation BOOLEAN,
                verbose BOOLEAN,
                max_iter INTEGER,
                settings JSON,
                enabled BOOLEAN,
                position INTEGER,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        conn.exec_driver_sql(
            "INSERT INTO agent_configs (project_id, crew, key, role, goal,"
            " backstory, settings, enabled, position) VALUES"
            " ('old_novel', 'scene_crew', 'director', '导演', '目标',"
            " '旧背景', '{}', 1, 0)"
        )
    engine.dispose()

    first = CrewConfigRepository(url)
    first.create_all()
    assert len(first.list_agents(project_id="old_novel")) == 1
    assert len(first.list_agents(project_id=DEFAULT_PROJECT_ID)) == 8

    # 第二次：模拟服务重启（全新 repository 实例，同一 URL）
    reset_repositories()
    reset_engines()
    second = CrewConfigRepository(url)
    second.create_all()  # 此时表已带外键，不应再触发迁移

    # old_novel 数据原样保留，不重复
    assert len(second.list_agents(project_id="old_novel")) == 1
    director = second.get_agent("director", project_id="old_novel")
    assert director["backstory"] == "旧背景"

    # demo 不重复播种
    assert len(second.list_agents(project_id=DEFAULT_PROJECT_ID)) == 8

    # 外键仍然在位（未发生二次 DROP/重建）
    inspector = sa.inspect(second.engine)
    fks = inspector.get_foreign_keys("agent_configs")
    assert any(
        fk.get("referred_table") == "projects" for fk in fks
    )

    reset_repositories()
    reset_engines()


def test_pragma_foreign_keys_enabled_per_connection(tmp_path):
    """SQLite 外键是连接级设置：get_engine 必须在每次连接建立后
    自动执行 PRAGMA foreign_keys = ON（base.py 的 event.listen）。
    回归点：connect 回调里若改用 sqlalchemy.text() 会直接 TypeError，
    外键静默失效，所有 FK/CASCADE 测试失去意义。"""
    reset_repositories()
    reset_engines()
    engine = get_engine(f"sqlite:///{tmp_path / 'pragma.db'}")

    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    # 再取一次连接（可能来自连接池）也必须处于开启状态
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1

    reset_repositories()
    reset_engines()


def test_upsert_project_explicit_update_still_works(repo):
    """Bug 1 的对照面：ensure_project 改为只 INSERT 后，
    upsert_project 的显式部分更新语义必须保持完好——
    只更新传入的字段，未传入的字段原样保留。"""
    repo.create_project("upsert_t", "原标题", "sci-fi", "原描述")

    result = repo.upsert_project("upsert_t", title="新标题", scene_count=3)
    assert result["title"] == "新标题"
    assert result["scene_count"] == 3
    # 未传入的字段不被触碰
    assert result["style"] == "sci-fi"
    assert result["description"] == "原描述"

    # 对不存在的项目，upsert 走新建分支（占位 title/style）
    result2 = repo.upsert_project("upsert_new", title="只给标题")
    assert result2["project_id"] == "upsert_new"
    assert result2["title"] == "只给标题"
    assert result2["style"] == "unknown"


def test_legacy_migration_skips_empty_project_id_rows(tmp_path):
    """旧库混有 project_id='' 的垃圾行时（生产中真实出现过），
    迁移不应被单条垃圾行阻塞：好数据保留，垃圾行丢弃，
    projects 表绝不出现空串行。"""
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'legacy_dirty.db'}"
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE agent_configs (
                id INTEGER PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL,
                crew VARCHAR(64) NOT NULL,
                key VARCHAR(64) NOT NULL,
                role TEXT NOT NULL,
                goal TEXT NOT NULL,
                backstory TEXT NOT NULL,
                allow_delegation BOOLEAN,
                verbose BOOLEAN,
                max_iter INTEGER,
                settings JSON,
                enabled BOOLEAN,
                position INTEGER,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        # 一条好数据 + 一条垃圾数据
        conn.exec_driver_sql(
            "INSERT INTO agent_configs (project_id, crew, key, role, goal,"
            " backstory, settings, enabled, position) VALUES"
            " ('good_novel', 'scene_crew', 'director', '导演', '目标',"
            " '好背景', '{}', 1, 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO agent_configs (project_id, crew, key, role, goal,"
            " backstory, settings, enabled, position) VALUES"
            " ('', 'scene_crew', 'garbage', 'r', 'g', 'b', '{}', 1, 0)"
        )
    engine.dispose()

    repo = CrewConfigRepository(url)
    repo.create_all()  # 不应抛 IntegrityError

    # 好数据保留
    director = repo.get_agent("director", project_id="good_novel")
    assert director is not None
    assert director["backstory"] == "好背景"
    # 垃圾行被丢弃
    assert repo.get_agent("garbage", project_id="") is None
    # projects 表没有空串行
    assert repo.get_project("") is None
    assert repo.project_exists("good_novel")

    reset_repositories()
    reset_engines()


def test_migration_when_only_task_table_is_legacy(tmp_path):
    """部分迁移：只有 task_configs 是旧形态、agent_configs 表不存在。
    迁移只处理存在的旧表，其余表正常新建。"""
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'legacy_task_only.db'}"
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(_LEGACY_TASK_DDL_NO_PID)
        conn.exec_driver_sql(
            "INSERT INTO task_configs (crew, key, description, expected_output,"
            " agent_key, context_keys, enabled, position) VALUES"
            " ('scene_crew', 'director_plan', '旧任务', '旧产出',"
            " 'director', '[]', 1, 0)"
        )
    engine.dispose()

    repo = CrewConfigRepository(url)
    repo.create_all()

    # legacy task 归入 demo 且保留
    task = repo.get_task("director_plan", project_id=DEFAULT_PROJECT_ID)
    assert task is not None
    assert task["description"] == "旧任务"

    # 两张表都建成、外键就位
    inspector = sa.inspect(repo.engine)
    for table in ("agent_configs", "task_configs"):
        assert inspector.has_table(table)
        fks = inspector.get_foreign_keys(table)
        assert any(fk.get("referred_table") == "projects" for fk in fks)

    # create_all 的 legacy 分支触发 demo seed
    assert len(repo.list_agents(project_id=DEFAULT_PROJECT_ID)) == 8
    assert repo.project_exists(DEFAULT_PROJECT_ID)

    reset_repositories()
    reset_engines()


# ---------------- ensure_project 幂等性 ----------------


def test_ensure_project_creates_placeholder(repo):
    """ensure_project 在 projects 表缺行时补一条占位记录"""
    repo.create_all()
    assert not repo.project_exists("placeholder_test")
    repo.ensure_project("placeholder_test")
    assert repo.project_exists("placeholder_test")
    proj = repo.get_project("placeholder_test")
    # 占位 title / style
    assert proj["title"] == "项目 placeholder_test"
    assert proj["style"] == "unknown"


def test_ensure_project_idempotent(repo):
    """重复 ensure_project 不抛异常，也不覆盖已有数据"""
    repo.create_project("idem", "真实标题", "sci-fi", "真实描述")
    repo.ensure_project("idem")
    proj = repo.get_project("idem")
    assert proj["title"] == "真实标题"
    assert proj["style"] == "sci-fi"


def test_regression_ensure_project_must_not_overwrite_metadata(repo):
    """回归（Bug 1）：ensure_project 曾错用 upsert_project（UPDATE 语义），
    导致 create_all → _ensure_all_project_ids_known → ensure_project
    把用户创建的 title/style 覆盖成占位符"项目 <pid>"/"unknown"。

    生产故障路径：创建项目（含 8 个自动播种的 agent）之后，任何后续操作
    （ensure_seeded / create_all / seed_from_yaml）都会经由
    _ensure_all_project_ids_known 对每个已出现的 project_id 调用
    ensure_project。修复后 ensure_project 必须是"只 INSERT 不 UPDATE"。
    """
    repo.create_project("novel_bug1", "星际迷航", "sci-fi", "外键验证")
    # create_project 已自动播种 8 个 agent，agent_configs 里已有该 project_id

    # 模拟生产中的后续操作链路（都会触发 _ensure_all_project_ids_known）
    repo.create_all()
    repo.ensure_seeded("novel_bug1")
    repo.ensure_project("novel_bug1")  # 直接调用也要幂等

    proj = repo.get_project("novel_bug1")
    assert proj["title"] == "星际迷航", (
        "ensure_project 不应覆盖已有项目的 title（Bug 1 回归）"
    )
    assert proj["style"] == "sci-fi", (
        "ensure_project 不应覆盖已有项目的 style（Bug 1 回归）"
    )
    assert proj["description"] == "外键验证"
