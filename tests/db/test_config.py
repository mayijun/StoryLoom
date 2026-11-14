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

    assert len(agents) == 5
    assert len(tasks) == 10
    assert agents[0]["key"] == "protagonist"
    assert tasks[0]["key"] == "director_plan"

    director = repo.get_agent("director")
    assert director["role"] == "叙事导演 · 场景意图设计"
    assert director["allow_delegation"] is None


def test_load_shapes_for_crewai(repo):
    repo.ensure_seeded()
    agents_config = repo.load_agents()
    tasks_config = repo.load_tasks()

    assert set(agents_config["director"]) == {
        "role",
        "goal",
        "backstory",
        "max_iter",
    }
    assert not {"surprise", "foreshadowing", "consistency"} & agents_config.keys()
    assert set(tasks_config) == {
        "director_plan",
        "actor_interaction",
        "prose_polish",
    }
    assert tasks_config["director_plan"]["expected_output"] == "JSON 场景意图包"

    meta = {row["key"]: row for row in repo.load_task_meta()}
    assert meta["director_plan"]["agent_key"] == "director"
    assert meta["director_plan"]["context_keys"] == []


def test_update_agent_is_persisted(repo):
    repo.ensure_seeded()
    repo.upsert_agent("director", backstory="新的导演背景")
    assert repo.load_agents()["director"]["backstory"] == "新的导演背景"


def test_missing_agent_falls_back_to_yaml(repo):
    """数据库里没有该 Agent 时，运行时读取使用 YAML 模板"""
    repo.ensure_seeded()
    assert repo.delete_agent("director")

    effective = repo.load_agents()
    assert effective["director"]["role"] == "叙事导演 · 场景意图设计"
    assert effective["director"]["backstory"]
    assert effective["director"]["max_iter"] == 6


def test_empty_agent_fields_fall_back_to_yaml(repo):
    """数据库里有该 Agent，但 prompt 字段为空时逐字段回退模板"""
    repo.ensure_seeded()
    repo.upsert_agent("director", goal="", backstory="项目自定义导演背景")

    effective = repo.load_agents()["director"]
    assert effective["backstory"] == "项目自定义导演背景"
    assert effective["goal"].startswith("先锚定当前时空")
    assert effective["role"] == "叙事导演 · 场景意图设计"


def test_disabled_agent_does_not_fall_back_to_yaml(repo):
    """显式停用的 Agent 视为项目明确设置，不再回退模板"""
    repo.ensure_seeded()
    repo.upsert_agent("prose", enabled=False)

    assert "prose" not in repo.load_agents()


def test_disabled_and_undefined_agent_errors_are_distinct(repo, monkeypatch):
    """报错需要区分「项目里显式停用」和「根本没有定义」"""
    repo.ensure_seeded()
    repo.upsert_agent("prose", enabled=False)

    monkeypatch.setenv("STORYLOOM_DATABASE_URL", repo.url)
    reset_repositories()
    reset_engines()

    from storyloom.crews.scene_crew.crew import SceneCrew

    crew = SceneCrew()
    with pytest.raises(KeyError, match="已停用"):
        crew.agent_for_key("prose")
    with pytest.raises(KeyError, match="未定义"):
        crew.agent_for_key("ghost_agent")


def test_missing_task_falls_back_to_yaml(repo):
    """数据库里没有该 Task 时，load_tasks / load_task_meta 使用 YAML 模板"""
    repo.ensure_seeded()
    assert repo.delete_task("director_plan")

    tasks = repo.load_tasks()
    assert "director_plan" in tasks
    assert tasks["director_plan"]["expected_output"] == "JSON 场景意图包"

    meta = {row["key"]: row for row in repo.load_task_meta()}
    assert meta["director_plan"]["agent_key"] == "director"
    assert meta["director_plan"]["context_keys"] == []

    actor_meta = meta["actor_interaction"]
    assert actor_meta["agent_key"] == "protagonist"
    assert actor_meta["context_keys"] == ["director_plan"]

    # 缺失任务按 YAML 相邻任务定位，顺序不能被打乱
    order = [row["key"] for row in repo.load_task_meta()]
    assert order == ["director_plan", "actor_interaction", "prose_polish"]


@pytest.mark.parametrize(
    "key",
    [
        "adjudicate_action",
        "npc_actions",
        "side_stage_direct",
        "wake_character",
        "wake_character_hint",
        "actor_interaction_secondary",
        "foreshadow_conflict",
    ],
)
def test_missing_prompt_template_falls_back_to_yaml(repo, key):
    """单 Agent 提示词模板缺失时仍能按项目读取 YAML 默认值"""
    repo.ensure_seeded()
    assert repo.delete_task(key)

    template = repo.load_task_template(key)
    assert template is not None
    assert template["description"].strip()


def test_empty_prompt_template_falls_back_to_yaml(repo):
    """数据库自定义 prompt 为空时回退模板默认值"""
    repo.ensure_seeded()
    repo.upsert_task("side_stage_direct", description="", expected_output="")

    template = repo.load_task_template("side_stage_direct")
    assert "侧台导演" in template["description"]
    assert "侧台事件 JSON" in template["expected_output"]


def test_project_prompt_overrides_are_isolated(repo):
    """一个项目自定义 prompt 不影响另一个项目"""
    repo.ensure_seeded("novel_a")
    repo.ensure_seeded("novel_b")
    repo.upsert_task(
        "adjudicate_action",
        project_id="novel_a",
        description="novel_a 专属裁决 {actor}",
        expected_output="JSON",
        enabled=False,
    )

    a = repo.load_task_template("adjudicate_action", project_id="novel_a")
    b = repo.load_task_template("adjudicate_action", project_id="novel_b")
    assert a["description"] == "novel_a 专属裁决 {actor}"
    assert "你是本作导演兼世界裁决者" in b["description"]

    # novel_a 删掉覆盖项后回退到模板，novel_b 始终不受影响
    repo.delete_task("adjudicate_action", project_id="novel_a")
    a = repo.load_task_template("adjudicate_action", project_id="novel_a")
    assert "你是本作导演兼世界裁决者" in a["description"]


def test_crew_runtime_uses_yaml_defaults_for_missing_config(repo, monkeypatch):
    """SceneCrew 运行时：数据库缺失的 Agent/Task 自动回退 YAML 模板"""
    repo.ensure_seeded()
    assert repo.delete_agent("offscreen_director")
    assert repo.delete_task("director_plan")
    assert repo.delete_task("adjudicate_action")

    monkeypatch.setenv("STORYLOOM_DATABASE_URL", repo.url)
    reset_repositories()
    reset_engines()

    from storyloom.crews.scene_crew.crew import SceneCrew

    crew = SceneCrew()
    assert (
        crew.agents_config["offscreen_director"]["role"]
        == "侧台导演 · 沉睡角色互动裁决"
    )
    assert "director_plan" in crew.tasks_config
    prompt = crew.task_prompt(
        "adjudicate_action",
        mode_rule="游戏模式",
        packet_contract="<contract>",
        phase="开场",
        goal="建立悬念",
        world_brief="世界状态",
        actor="主角",
        action="推门",
        target="门",
    )
    assert "你是本作导演兼世界裁决者" in prompt
    assert "{actor}" not in prompt

    # 回退的标准任务仍排在最前，下游任务的 context 依赖正常解析
    tasks = crew.crew().tasks
    assert len(tasks) == 3
    assert tasks[0].description.startswith("你是本作导演兼创作总指挥")
    assert len(tasks[1].context) == 1
    assert len(tasks[2].context) == 1


def test_agent_prompt_with_unescaped_braces_does_not_crash(repo, monkeypatch):
    """自定义 Agent prompt 含未转义花括号时保留原文，不中断 Crew 构建"""
    repo.ensure_seeded()
    repo.upsert_agent("protagonist", backstory="遵循 {未知规则} 的风格")

    monkeypatch.setenv("STORYLOOM_DATABASE_URL", repo.url)
    reset_repositories()
    reset_engines()

    from storyloom.crews.scene_crew.crew import SceneCrew
    from storyloom.memory.models import CharacterAsset

    agent = SceneCrew().build_protagonist(
        CharacterAsset(
            name="林",
            importance_tier="primary",
            persona="谨慎",
            motivation="查明真相",
        )
    )
    assert "遵循 {未知规则} 的风格" in agent.backstory


def test_narrative_prompt_builders_use_project_overrides(repo, monkeypatch):
    """引擎实际调用的 prompt 构建方法读取项目自定义模板"""
    repo.ensure_seeded()
    repo.upsert_task(
        "director_plan",
        description="项目导演模板 {mode_hint}",
        expected_output="x",
    )
    repo.upsert_task(
        "prose_polish",
        description="项目正文模板 {actor_log}",
        expected_output="x",
    )
    repo.upsert_task(
        "actor_interaction",
        description="项目角色模板 {character_name}",
        expected_output="{character_name} 输出",
    )
    repo.upsert_task(
        "foreshadow_conflict",
        description="项目伏笔模板 {foreshadow_context}",
        expected_output="x",
    )

    monkeypatch.setenv("STORYLOOM_DATABASE_URL", repo.url)
    reset_repositories()
    reset_engines()

    from types import SimpleNamespace

    from storyloom.crews.scene_crew.crew import SceneCrew
    from storyloom.engine.narrative import NarrativeEngine

    class _StubAssembler:
        scene_brief = "雨夜"

        def build(self, *args, **kwargs):
            return "共享上下文"

        def intent_block(self):
            return "导演意图"

    engine = NarrativeEngine(crew=SceneCrew())
    director_prompt = engine._build_director_prompt(
        assembler=_StubAssembler(), mode="game", pre_context=None
    )
    assert director_prompt.strip() == "项目导演模板 游戏模式：玩家刚刚行动完毕，GM 已裁决（见 pre_context），你在此基础上做叙事意图规划。action_text 是玩家行动。"

    prose_prompt = engine._build_prose_prompt(
        actor_log="林推门",
        director_json={},
        mode="director",
        project=SimpleNamespace(style="冷峻"),
    )
    assert prose_prompt.strip() == "项目正文模板 林推门"

    assert (
        engine.crew.task_prompt("actor_interaction", character_name="林").strip()
        == "项目角色模板 林"
    )
    assert (
        engine.crew.task_prompt(
            "foreshadow_conflict", foreshadow_context='{"a": 1}'
        ).strip()
        == '项目伏笔模板 {"a": 1}'
    )


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
    assert len(std.agents) == 6
    assert len(std.tasks) == 4
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
    assert len(crew.crew().tasks) == 2


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
    assert len(repo.list_agents()) == 5
    assert len(repo.list_agents(project_id="novel2")) == 5


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
    assert len(repo.list_agents()) == 5
    reset_repositories()
    reset_engines()
