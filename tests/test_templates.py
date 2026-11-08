"""试用模板（templates/）单元测试（无需 API Key）。

覆盖：
- 内置模板注册与摘要列表
- 模板内嵌扩展的 manifest 校验（map mod / skill）
- ``apply_template`` 落库：项目、角色、地点、伏笔、章节、统计字段
- 幂等：重复应用 / 已有资产的跳过保护
- 未知模板报错
- 试用项目可删除清理
- ``ExtensionRegistry`` 从模板加载扩展且不重复
- Engine / Router 层的模板列表与应用接口
- examples/ 不再残留固定 demo YAML
"""

import asyncio

import pytest
from fastapi import HTTPException

from storyloom.db import CrewConfigRepository, reset_engines, reset_repositories
from storyloom.extensions.host import ExtensionRegistry
from storyloom.extensions.manifest import discover
from storyloom.templates import (
    TEMPLATES,
    Template,
    apply_template,
    get_template,
    list_templates,
    register,
)

TEMPLATE_ID = "xianxia_system"


@pytest.fixture
def repo(tmp_path):
    """每个测试独立的临时 SQLite 文件。"""
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'templates.db'}"
    yield CrewConfigRepository(url)
    reset_repositories()
    reset_engines()


@pytest.fixture
def api_engine(tmp_path, monkeypatch):
    """隔离的全局引擎：独立 DB + 清空运行时缓存与扩展缓存。"""
    monkeypatch.setenv(
        "STORYLOOM_DATABASE_URL", f"sqlite:///{tmp_path / 'engine.db'}"
    )
    reset_repositories()
    reset_engines()

    from storyloom.api.engine import engine

    engine._project_runtime.clear()
    engine.memories.clear()
    engine.rags.clear()
    engine.game_states.clear()
    engine.game_memories.clear()
    engine.last_turns.clear()
    engine.extension_registry.clear_cache()
    yield engine
    engine._project_runtime.clear()
    engine.memories.clear()
    engine.rags.clear()
    engine.game_states.clear()
    engine.game_memories.clear()
    engine.last_turns.clear()
    engine.extension_registry.clear_cache()
    reset_repositories()
    reset_engines()


# ---------------- 模板注册与元数据 ----------------


def test_builtin_template_is_registered():
    template = get_template(TEMPLATE_ID)
    assert template is not None
    assert template.title == "青云宗 · 签到有债"
    assert template.style == "仙侠世界 · 现实后果 · 群像"
    assert template.description


def test_template_asset_counts_and_order():
    template = get_template(TEMPLATE_ID)
    assert len(template.characters) == 5
    assert len(template.locations) == 6
    assert len(template.foreshadowings) == 3
    assert len(template.chapters) == 3

    # 前端 / WorldState 以「玩家」为视角锚点，必须排第一
    assert template.characters[0]["name"] == "玩家"
    # 所有角色初始放在第一个地点，第一地点必须是「演武场」
    assert template.locations[0]["name"] == "演武场"
    # 护卫拦截按精确名「地牢」命中
    assert "地牢" in [loc["name"] for loc in template.locations]
    # 伏笔使用固定 ID，方便状态机测试
    assert [f["foreshadow_id"] for f in template.foreshadowings] == [
        "fs_ninth_slot",
        "fs_black_vein",
        "fs_devouring_nail",
    ]


def test_list_templates_returns_summaries():
    summaries = list_templates()
    by_id = {t["template_id"]: t for t in summaries}
    assert TEMPLATE_ID in by_id
    summary = by_id[TEMPLATE_ID]
    assert set(summary) == {"template_id", "title", "style", "description"}
    assert summary["title"] == "青云宗 · 签到有债"


def test_get_unknown_template_returns_none():
    assert get_template("no_such_template") is None


def test_register_custom_template():
    """注册表对外可用：自定义模板可注册并按 id 取回（清理后不影响内置模板）。"""
    custom = Template(
        template_id="unit_test_tpl",
        title="单元测试模板",
        style="test",
    )
    try:
        register(custom)
        assert get_template("unit_test_tpl") is custom
        assert any(
            t["template_id"] == "unit_test_tpl" for t in list_templates()
        )
    finally:
        TEMPLATES.pop("unit_test_tpl", None)


# ---------------- 内嵌扩展 ----------------


def test_embedded_extensions_are_valid_manifests():
    template = get_template(TEMPLATE_ID)
    manifests = template.extension_manifests()
    by_id = {m.id: m for m in manifests}

    assert set(by_id) == {"map_xianxia", "skill_xianxia"}
    assert by_id["map_xianxia"].kind == "mod"
    assert by_id["skill_xianxia"].kind == "skill"

    map_data = by_id["map_xianxia"].contributes["map"]
    route = next(
        r
        for r in map_data["routes"]
        if r["from"] == "演武场" and r["to"] == "杂役院"
    )
    assert route["minutes"] == 8
    # LLM 工具必须 read_only（manifest 校验已强制，这里再确认数据本身）
    assert all(t["read_only"] for t in by_id["map_xianxia"].contributes["tools"])


def test_examples_dir_no_longer_ships_demo_yaml():
    """demo 的 map/skill 已内嵌进模板，examples/ 下不应再有固定 YAML。"""
    assert discover() == []


# ---------------- apply_template 落库 ----------------


def test_apply_template_creates_project(repo):
    applied = apply_template(TEMPLATE_ID, "pid_ok", repo)

    assert applied is True
    meta = repo.get_project("pid_ok")
    template = get_template(TEMPLATE_ID)
    assert meta["title"] == template.title
    assert meta["style"] == template.style
    assert meta["description"] == template.description


def test_apply_template_writes_all_assets(repo):
    apply_template(TEMPLATE_ID, "pid_assets", repo)

    characters = repo.list_characters("pid_assets")
    assert [c["name"] for c in characters] == [
        "玩家",
        "苏清雪",
        "秦无咎",
        "杂役管事",
        "执法堂守卫",
    ]
    # 主角秘密必须落库（记忆 A15 依赖）
    player = next(c for c in characters if c["name"] == "玩家")
    assert "荒古圣体" in player["secrets"]

    locations = repo.list_locations("pid_assets")
    assert [loc["name"] for loc in locations] == [
        "演武场",
        "杂役院",
        "藏经阁",
        "丹房",
        "地牢",
        "后山禁地",
    ]

    foreshadowings = repo.list_foreshadowings("pid_assets")
    assert {f["foreshadow_id"] for f in foreshadowings} == {
        "fs_ninth_slot",
        "fs_black_vein",
        "fs_devouring_nail",
    }
    assert all(f["status"] == "planted" for f in foreshadowings)


def test_apply_template_chapters_positions_and_status(repo):
    apply_template(TEMPLATE_ID, "pid_chapters", repo)

    chapters = repo.list_chapters("pid_chapters")
    assert [c["title"] for c in chapters] == [
        "杂役院的第一笔",
        "大比之日，人人有账",
        "第九格的债主",
    ]
    assert [c["position"] for c in chapters] == [0, 1, 2]
    assert all(c["status"] == "draft" for c in chapters)
    assert all(c["outline"] for c in chapters)


def test_apply_template_syncs_project_stats(repo):
    apply_template(TEMPLATE_ID, "pid_stats", repo)

    meta = repo.get_project("pid_stats")
    assert meta["character_count"] == 5
    assert meta["foreshadowing_count"] == 3


def test_apply_template_custom_title(repo):
    apply_template(TEMPLATE_ID, "pid_title", repo, title="我的试玩项目")

    meta = repo.get_project("pid_title")
    assert meta["title"] == "我的试玩项目"
    # 文风/描述仍来自模板
    assert meta["style"] == get_template(TEMPLATE_ID).style


def test_apply_template_is_idempotent_and_preserves_edits(repo):
    assert apply_template(TEMPLATE_ID, "pid_twice", repo) is True
    # 模拟用户试用中的修改
    repo.upsert_character(
        "pid_twice", "玩家", "primary", "用户改写的人设", "新动机", "新秘密"
    )

    # 第二次应用应跳过写入
    assert apply_template(TEMPLATE_ID, "pid_twice", repo) is False

    characters = repo.list_characters("pid_twice")
    assert len(characters) == 5  # 不重复写入
    player = next(c for c in characters if c["name"] == "玩家")
    assert player["persona"] == "用户改写的人设"  # 不覆盖用户修改


def test_apply_template_skips_when_project_already_has_characters(repo):
    repo.create_project("pid_existing", "已有项目", "sci-fi")
    repo.upsert_character("pid_existing", "既有角色", "primary", "p", "m")

    assert apply_template(TEMPLATE_ID, "pid_existing", repo) is False
    assert [c["name"] for c in repo.list_characters("pid_existing")] == [
        "既有角色"
    ]
    # 已有角色时不应补写模板的其它资产
    assert repo.list_locations("pid_existing") == []


def test_apply_unknown_template_raises(repo):
    repo.create_all()
    with pytest.raises(ValueError, match="模板不存在"):
        apply_template("ghost_template", "pid_ghost", repo)
    assert not repo.project_exists("pid_ghost")


def test_two_applied_projects_can_coexist(repo):
    """同一模板应用两次时章节 ID 不冲突，两个项目各自完整。"""
    apply_template(TEMPLATE_ID, "pid_a", repo)
    apply_template(TEMPLATE_ID, "pid_b", repo)

    chapters_a = repo.list_chapters("pid_a")
    chapters_b = repo.list_chapters("pid_b")
    assert len(chapters_a) == len(chapters_b) == 3
    assert [c["title"] for c in chapters_a] == [c["title"] for c in chapters_b]
    # 章节 ID 全局唯一
    ids_a = {c["chapter_id"] for c in chapters_a}
    ids_b = {c["chapter_id"] for c in chapters_b}
    assert ids_a.isdisjoint(ids_b)


def test_applied_template_project_can_be_deleted(repo):
    """试用结束后删除项目即可清理，不残留固定数据。"""
    apply_template(TEMPLATE_ID, "pid_cleanup", repo)
    assert repo.project_exists("pid_cleanup")

    assert repo.delete_project("pid_cleanup") is True
    assert not repo.project_exists("pid_cleanup")


# ---------------- ExtensionRegistry 集成 ----------------


def test_extension_registry_loads_template_extensions_once(tmp_path):
    registry = ExtensionRegistry(root=str(tmp_path))

    first = registry.manifests()
    ids = [m.id for m in first]
    assert ids.count("map_xianxia") == 1
    assert ids.count("skill_xianxia") == 1

    # 多次调用不重复加载
    second = registry.manifests()
    assert [m.id for m in second] == ids

    host = registry.for_instance("inst-1")
    resolved = host.resolve()
    assert any(s["id"] == "skill_xianxia" for s in resolved["skills"])
    assert any(m["id"] == "map_xianxia" for m in resolved["mods"])
    assert resolved["travel_overrides"]["演武场->杂役院"] == 8
    assert resolved["travel_overrides"]["地牢->演武场"] == 6


def test_extension_registry_reload_after_clear_cache(tmp_path):
    registry = ExtensionRegistry(root=str(tmp_path))
    registry.manifests()

    registry.clear_cache()
    ids = [m.id for m in registry.manifests()]
    assert ids.count("map_xianxia") == 1
    assert ids.count("skill_xianxia") == 1


# ---------------- Engine 层 ----------------


def test_engine_list_templates(api_engine):
    summaries = api_engine.list_templates()
    assert any(t["template_id"] == TEMPLATE_ID for t in summaries)


def test_engine_apply_template_creates_cached_project(api_engine):
    meta = api_engine.apply_template(TEMPLATE_ID)

    pid = meta["project_id"]
    assert pid.startswith(f"tpl_{TEMPLATE_ID}_")
    assert meta["title"] == get_template(TEMPLATE_ID).title
    assert meta["character_count"] == 5

    # 列表可见
    assert any(p["project_id"] == pid for p in api_engine.list_projects())
    # 运行时缓存已就绪
    assert pid in api_engine._project_runtime
    assert pid in api_engine.memories
    assert pid in api_engine.rags


def test_engine_apply_template_generates_distinct_projects(api_engine):
    first = api_engine.apply_template(TEMPLATE_ID)
    second = api_engine.apply_template(TEMPLATE_ID)

    assert first["project_id"] != second["project_id"]
    pids = {p["project_id"] for p in api_engine.list_projects()}
    assert {first["project_id"], second["project_id"]} <= pids


def test_engine_apply_unknown_template_raises(api_engine):
    with pytest.raises(ValueError, match="模板不存在"):
        api_engine.apply_template("ghost_template")


# ---------------- Router 层 ----------------


@pytest.fixture
def templates_router(api_engine):
    from storyloom.api.routers import templates as router

    return router


def test_router_list_templates(templates_router):
    response = asyncio.run(templates_router.list_templates())
    ids = [t.template_id for t in response.templates]
    assert TEMPLATE_ID in ids


def test_router_apply_template(templates_router):
    from storyloom.api.schemas import TemplateApplyRequest

    view = asyncio.run(
        templates_router.apply_template(
            TEMPLATE_ID, TemplateApplyRequest(title=None)
        )
    )
    assert view.project_id.startswith(f"tpl_{TEMPLATE_ID}_")
    assert view.title == get_template(TEMPLATE_ID).title
    assert view.character_count == 5
    assert view.foreshadowing_count == 3


def test_router_apply_unknown_template_returns_404(templates_router):
    from storyloom.api.schemas import TemplateApplyRequest

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            templates_router.apply_template(
                "ghost_template", TemplateApplyRequest()
            )
        )
    assert exc_info.value.status_code == 404
