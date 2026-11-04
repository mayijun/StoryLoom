"""数据库配置层单元测试（无需 API Key）"""

import pytest

from storyloom.db import (
    CrewConfigRepository,
    reset_engines,
    reset_repositories,
)


@pytest.fixture
def repo(tmp_path):
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'config.db'}"
    yield CrewConfigRepository(url)
    reset_repositories()
    reset_engines()


def test_seed_from_yaml(repo):
    repo.ensure_seeded()
    agents = repo.list_agents()
    tasks = repo.list_tasks()

    assert len(agents) == 8
    assert len(tasks) == 6
    assert agents[0]["key"] == "protagonist"
    assert tasks[0]["key"] == "surprise_proposal"

    director = repo.get_agent("director")
    assert director["role"] == "导演"
    assert director["allow_delegation"] is None


def test_load_shapes_for_crewai(repo):
    repo.ensure_seeded()
    agents_config = repo.load_agents()
    tasks_config = repo.load_tasks()

    assert set(agents_config["surprise"]) == {"role", "goal", "backstory"}
    assert tasks_config["director_plan"]["expected_output"] == "JSON 场景意图包"

    meta = {row["key"]: row for row in repo.load_task_meta()}
    assert meta["director_plan"]["agent_key"] == "director"
    assert meta["director_plan"]["context_keys"] == [
        "surprise_proposal",
        "foreshadowing_ops",
    ]


def test_update_agent_is_persisted(repo):
    repo.ensure_seeded()
    repo.upsert_agent("director", backstory="新的导演背景")
    assert repo.load_agents()["director"]["backstory"] == "新的导演背景"


def test_add_agent_and_task_without_code_change(repo, monkeypatch):
    repo.ensure_seeded()
    repo.upsert_agent(
        "critic",
        role="文风批评家",
        goal="挑出陈词滥调",
        backstory="你是苛刻的编辑",
    )
    repo.upsert_task(
        "style_review",
        description="审查文风",
        expected_output="问题清单",
        agent_key="critic",
        context_keys=["prose_polish"],
    )

    monkeypatch.setenv("STORYLOOM_DATABASE_URL", repo.url)
    reset_repositories()
    reset_engines()

    from storyloom.crews.scene_crew.crew import SceneCrew

    crew = SceneCrew()
    std = crew.crew()

    assert "critic" in crew.agents_config
    assert "style_review" in crew.tasks_config
    assert len(std.agents) == 9
    assert len(std.tasks) == 7
    assert std.tasks[-1].description == "审查文风"


def test_disabled_task_is_skipped(repo, monkeypatch):
    repo.ensure_seeded()
    repo.upsert_task("prose_polish", enabled=False)

    monkeypatch.setenv("STORYLOOM_DATABASE_URL", repo.url)
    reset_repositories()
    reset_engines()

    from storyloom.crews.scene_crew.crew import SceneCrew

    crew = SceneCrew()
    assert "prose_polish" not in crew.tasks_config
    assert len(crew.crew().tasks) == 5


def test_project_isolation(repo):
    """不同项目各自拥有独立的 Agent / Task，默认项目为 demo"""
    repo.ensure_seeded()
    repo.ensure_seeded("novel2")
    repo.upsert_agent(
        "director", project_id="novel2", backstory="novel2 专属导演"
    )
    repo.upsert_task(
        "style_review",
        project_id="novel2",
        description="novel2 文风审查",
        expected_output="问题清单",
    )

    assert repo.get_agent("director")["backstory"] != "novel2 专属导演"
    assert (
        repo.get_agent("director", project_id="novel2")["backstory"]
        == "novel2 专属导演"
    )
    assert repo.get_task("style_review") is None
    assert (
        repo.get_task("style_review", project_id="novel2")["description"]
        == "novel2 文风审查"
    )
    assert len(repo.list_agents()) == 8
    assert len(repo.list_agents(project_id="novel2")) == 8


def test_legacy_db_migrated_into_demo_project(tmp_path):
    """旧库（无 project_id 列）升级：数据自动归入 demo 项目"""
    import sqlalchemy as sa

    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    legacy_engine = sa.create_engine(url)
    with legacy_engine.begin() as conn:
        conn.exec_driver_sql(
            """
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
        )
        conn.exec_driver_sql(
            "INSERT INTO agent_configs (crew, key, role, goal, backstory,"
            " settings, enabled, position) VALUES"
            " ('scene_crew', 'director', '导演', '目标', '背景', '{}', 1, 2)"
        )

    repo = CrewConfigRepository(url)
    repo.ensure_seeded()

    # 旧数据保留并归入 demo；其余 Agent 由种子补齐
    director = repo.get_agent("director")
    assert director["project_id"] == "demo"
    assert director["backstory"] == "背景"
    assert len(repo.list_agents()) == 8
    reset_repositories()
    reset_engines()
