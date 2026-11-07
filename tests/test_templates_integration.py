"""试用模板应用的 HTTP 集成测试。

与 ``test_templates.py``（单元测试）互补：这里通过 ``TestClient`` 走真实的
FastAPI 应用与路由，验证用户从 Web 界面点「试用模板」后能得到什么：

1. 模板列表 → 应用 → 项目出现在项目列表
2. 应用后的资产 / 章节 / 覆核通过既有 API 可见
3. 模板内嵌扩展（地图 + 文风）通过扩展解析接口生效
4. 游戏模式能用模板地图移动（旅行耗时来自内嵌 mod）
5. 导出 / 记忆回填直接消费模板资产
6. 试用结束删除项目即可清理，扩展仍可用
"""

import pytest
from fastapi.testclient import TestClient

from storyloom.db import reset_engines, reset_repositories
from storyloom.saves.service import SaveService

TEMPLATE_ID = "xianxia_system"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """真实 app + 独立 SQLite 文件；清空引擎运行时缓存。"""
    reset_repositories()
    reset_engines()
    monkeypatch.setenv(
        "STORYLOOM_DATABASE_URL", f"sqlite:///{tmp_path / 'tpl_api.db'}"
    )

    from storyloom.api.engine import engine
    from storyloom.api.main import app

    engine._project_runtime.clear()
    engine.memories.clear()
    engine.rags.clear()
    engine.game_states.clear()
    engine.game_memories.clear()
    engine.last_turns.clear()
    engine.extension_registry.clear_cache()
    engine.save_service = SaveService(root=str(tmp_path / "saves"))

    with TestClient(app) as test_client:
        yield test_client

    reset_repositories()
    reset_engines()


def _apply(client, title=None):
    payload = {"title": title} if title is not None else {}
    resp = client.post(f"/api/templates/{TEMPLATE_ID}/apply", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------- 列表 → 应用 → 项目可见 ----------------


def test_template_list_endpoint(client):
    resp = client.get("/api/templates/")
    assert resp.status_code == 200, resp.text
    templates = {t["template_id"]: t for t in resp.json()["templates"]}
    assert TEMPLATE_ID in templates
    tpl = templates[TEMPLATE_ID]
    assert tpl["title"] == "系统逼我当仙尊"
    assert tpl["style"] == "爽文仙侠 · 系统流"
    assert tpl["description"]


def test_apply_template_creates_listed_project(client):
    view = _apply(client)
    pid = view["project_id"]
    assert pid.startswith(f"tpl_{TEMPLATE_ID}_")
    assert view["title"] == "系统逼我当仙尊"
    assert view["character_count"] == 5
    assert view["foreshadowing_count"] == 3

    listed = client.get("/api/projects/").json()["projects"]
    assert pid in [p["project_id"] for p in listed]

    detail = client.get(f"/api/projects/{pid}")
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["characters"]) == 5
    assert len(body["locations"]) == 6
    assert len(body["foreshadowings"]) == 3


def test_apply_template_with_custom_title(client):
    view = _apply(client, title="我的试玩")
    assert view["title"] == "我的试玩"
    detail = client.get(f"/api/projects/{view['project_id']}").json()
    assert detail["title"] == "我的试玩"
    assert detail["style"] == "爽文仙侠 · 系统流"


def test_apply_unknown_template_returns_404(client):
    resp = client.post("/api/templates/ghost/apply", json={})
    assert resp.status_code == 404


def test_template_apply_does_not_touch_existing_projects(client):
    blank = client.post(
        "/api/projects/",
        json={"title": "空白项目", "style": "悬疑", "description": ""},
    ).json()
    _apply(client)

    blank_id = blank["project_id"]
    detail = client.get(f"/api/projects/{blank_id}").json()
    assert detail["characters"] == []
    assert detail["locations"] == []


# ---------------- 资产 / 章节通过既有 API 可见 ----------------


def test_applied_assets_visible_through_assets_api(client):
    pid = _apply(client)["project_id"]

    characters = client.get(f"/api/projects/{pid}/assets/characters").json()
    assert [c["name"] for c in characters] == [
        "玩家",
        "苏清雪",
        "秦无咎",
        "杂役管事",
        "执法堂守卫",
    ]

    locations = client.get(f"/api/projects/{pid}/assets/locations").json()
    assert [loc["name"] for loc in locations] == [
        "演武场",
        "杂役院",
        "藏经阁",
        "丹房",
        "地牢",
        "后山禁地",
    ]

    foreshadowings = client.get(
        f"/api/projects/{pid}/assets/foreshadowings"
    ).json()
    assert {f["foreshadow_id"] for f in foreshadowings} == {
        "fs_ninth_slot",
        "fs_black_vein",
        "fs_devouring_nail",
    }
    assert all(f["status"] == "planted" for f in foreshadowings)


def test_applied_chapters_visible_and_ordered(client):
    pid = _apply(client)["project_id"]

    chapters = client.get(f"/api/projects/{pid}/chapters").json()
    assert [c["title"] for c in chapters] == [
        "签到荒古圣体",
        "大比之日，全宗都在看我",
        "师姐，我真不是隐藏大佬",
    ]
    assert [c["position"] for c in chapters] == [0, 1, 2]
    assert all(c["status"] == "draft" for c in chapters)

    first = client.get(
        f"/api/projects/{pid}/chapters/{chapters[0]['chapter_id']}"
    ).json()
    assert first["title"] == "签到荒古圣体"


def test_foreshadow_transition_works_on_template_assets(client):
    """模板伏笔可直接走既有状态机接口。"""
    pid = _apply(client)["project_id"]

    resp = client.post(
        f"/api/projects/{pid}/assets/foreshadowings/fs_ninth_slot/transition",
        json={"action": "reinforce"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "reinforced"

    # 非法流转仍被保护
    illegal = client.post(
        f"/api/projects/{pid}/assets/foreshadowings/fs_ninth_slot/transition",
        json={"action": "resolve"},
    )
    assert illegal.status_code == 409


# ---------------- 内嵌扩展 ----------------


def test_embedded_extensions_resolved_via_api(client):
    resp = client.post(
        "/runtime/v1/extensions/resolve", json={"instance_id": "tpl_inst"}
    )
    assert resp.status_code == 200, resp.text
    resolved = resp.json()

    assert any(s["id"] == "skill_xianxia" for s in resolved["skills"])
    assert any(m["id"] == "map_xianxia" for m in resolved["mods"])
    assert resolved["travel_overrides"]["演武场->杂役院"] == 8
    assert resolved["travel_overrides"]["地牢->演武场"] == 6


def test_game_mode_moves_using_template_map(client):
    pid = _apply(client)["project_id"]

    initial = client.get(
        f"/runtime/v1/{pid}/state", params={"instance_id": "g1"}
    ).json()["state"]
    assert initial["mode"] == "game"
    assert initial["time_minutes"] == 480
    assert initial["turn"] == 0
    assert len(initial["characters"]) == 5
    assert {c["location"] for c in initial["characters"].values()} == {
        "演武场"
    }

    # 第 1 回合：首回合 boot 会把地图 mod 的出口注入世界
    observe = client.post(
        f"/runtime/v1/{pid}/turn",
        json={"instance_id": "g1", "actor": "玩家", "text": "观察四周"},
    )
    assert observe.status_code == 200, observe.text
    assert observe.json()["status"] == "ok"

    # 第 2 回合：旅行耗时来自模板内嵌的地图 mod（演武场→藏经阁 10 分钟）
    move = client.post(
        f"/runtime/v1/{pid}/turn",
        json={"instance_id": "g1", "actor": "玩家", "text": "前往藏经阁"},
    )
    assert move.status_code == 200, move.text
    moved = move.json()
    assert moved["status"] == "ok"
    assert moved["state"]["characters"]["玩家"]["location"] == "藏经阁"
    assert moved["state"]["time_minutes"] == 490
    assert "路上花了10分钟" in moved["text"]


# ---------------- 导出 / 记忆 ----------------


def test_export_uses_template_chapters(client):
    pid = _apply(client)["project_id"]

    md = client.get(f"/api/projects/{pid}/export", params={"format": "md"})
    assert md.status_code == 200, md.text
    text = md.text
    assert text.startswith("# 系统逼我当仙尊")
    assert "> 文风：爽文仙侠 · 系统流" in text
    assert "## 第1章 签到荒古圣体" in text
    assert "## 第3章 师姐，我真不是隐藏大佬" in text

    txt = client.get(f"/api/projects/{pid}/export", params={"format": "txt"})
    assert txt.status_code == 200
    assert "## " not in txt.text
    assert "签到荒古圣体" in txt.text


def test_memory_backfill_consumes_template_assets(client):
    pid = _apply(client)["project_id"]

    memory = client.get(f"/api/projects/{pid}/memory")
    assert memory.status_code == 200, memory.text
    body = memory.json()
    # 5 角色 + 5 条秘密 + 6 地点 → 至少 16 条归档
    assert body["counts"]["archive"] >= 16
    assert body["tiers"]
    assert isinstance(body["prompt_block"], str)


# ---------------- 多次应用 / 清理 ----------------


def test_two_template_projects_coexist(client):
    first = _apply(client)["project_id"]
    second = _apply(client)["project_id"]
    assert first != second

    for pid in (first, second):
        chapters = client.get(f"/api/projects/{pid}/chapters").json()
        assert len(chapters) == 3

    ids_a = {
        c["chapter_id"]
        for c in client.get(f"/api/projects/{first}/chapters").json()
    }
    ids_b = {
        c["chapter_id"]
        for c in client.get(f"/api/projects/{second}/chapters").json()
    }
    assert ids_a.isdisjoint(ids_b)


def test_delete_template_project_cleans_up(client):
    pid = _apply(client)["project_id"]

    deleted = client.delete(f"/api/projects/{pid}")
    assert deleted.status_code == 200
    assert deleted.json()["project_id"] == pid

    assert client.get(f"/api/projects/{pid}").status_code == 404
    listed = client.get("/api/projects/").json()["projects"]
    assert pid not in [p["project_id"] for p in listed]

    # 模板扩展属于全局只读数据，删除试用项目后仍可解析
    resolved = client.post(
        "/runtime/v1/extensions/resolve", json={"instance_id": "after_delete"}
    )
    assert resolved.status_code == 200
    assert any(
        m["id"] == "map_xianxia" for m in resolved.json()["mods"]
    )
