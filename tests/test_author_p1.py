"""作者模式 P1 测试

覆盖：
- 伏笔状态显式流转 API（合法 / 非法 / 不存在）
- 小说导出 Markdown / TXT（章节组织 + 未归属场景 + 下载头）
- 项目指标 API（质量分 / 耗时 / 模型与 Agent 调用量聚合）
- Agent / Task 配置导出 / 导入（merge / overwrite）/ 跨项目复制
"""

import pytest
from fastapi.testclient import TestClient

from storyloom.db import (
    CrewConfigRepository,
    reset_engines,
    reset_repositories,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'p1.db'}"
    monkeypatch.setenv("STORYLOOM_DATABASE_URL", url)

    repo = CrewConfigRepository(url)
    repo.create_all()
    repo.create_project("novel_p", "雾中旅人", "film_narrative")

    from storyloom.api.main import app

    yield TestClient(app), repo
    reset_repositories()
    reset_engines()


def _seed_foreshadowing(repo, fid="fs_test01", status="planted"):
    repo.upsert_foreshadowing(
        "novel_p",
        foreshadow_id=fid,
        description="旅店墙上被涂改的航海图",
        planted_in_scene="scene_1",
        target_revelation="航海图指向真正的宝藏",
        status=status,
    )


# ============================================================
# 伏笔状态流转
# ============================================================

def test_foreshadow_transition_reinforce(client):
    c, repo = client
    _seed_foreshadowing(repo)
    resp = c.post(
        "/api/projects/novel_p/assets/foreshadowings/fs_test01/transition",
        json={"action": "reinforce"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "reinforced"
    assert body["reinforcement_count"] == 1
    # 落库
    row = repo.get_foreshadowing("fs_test01", "novel_p")
    assert row["status"] == "reinforced"
    assert row["reinforcement_count"] == 1


def test_foreshadow_transition_full_lifecycle(client):
    c, repo = client
    _seed_foreshadowing(repo)
    for action, expect in [
        ("activate", "activated"),
        ("resolve", "resolved"),
        ("replant", "planted"),
        ("subvert", "subverted"),
        ("replant", "planted"),
        ("abandon", "abandoned"),
    ]:
        resp = c.post(
            "/api/projects/novel_p/assets/foreshadowings/fs_test01/transition",
            json={"action": action},
        )
        assert resp.status_code == 200, f"{action}: {resp.text}"
        assert resp.json()["status"] == expect
    # replant 后强化计数被重置
    row = repo.get_foreshadowing("fs_test01", "novel_p")
    assert row["reinforcement_count"] == 0


def test_foreshadow_transition_illegal_409(client):
    c, repo = client
    _seed_foreshadowing(repo, status="planted")
    # planted 不能直接 resolve（只允许 activated → resolved）
    resp = c.post(
        "/api/projects/novel_p/assets/foreshadowings/fs_test01/transition",
        json={"action": "resolve"},
    )
    assert resp.status_code == 409
    assert "resolve" in resp.json()["detail"]


def test_foreshadow_transition_not_found(client):
    c, _ = client
    resp = c.post(
        "/api/projects/novel_p/assets/foreshadowings/fs_nope/transition",
        json={"action": "activate"},
    )
    assert resp.status_code == 404


def test_foreshadow_transition_bad_action_422(client):
    c, repo = client
    _seed_foreshadowing(repo)
    resp = c.post(
        "/api/projects/novel_p/assets/foreshadowings/fs_test01/transition",
        json={"action": "explode"},
    )
    assert resp.status_code == 422


# ============================================================
# 小说导出
# ============================================================

def _seed_novel(repo):
    repo.create_chapter("ch_1", "novel_p", "雾起", outline="开场", position=0)
    repo.create_chapter("ch_2", "novel_p", "灯塔", position=1)
    repo.create_scene(
        "scene_1", "novel_p", brief="主角到旅店", prose="雾把码头吞了一半。",
        chapter_id="ch_1",
    )
    repo.create_scene(
        "scene_2", "novel_p", brief="遇见老板娘", prose="她擦着杯子，没有抬头。",
        chapter_id="ch_1",
    )
    repo.create_scene(
        "scene_3", "novel_p", brief="独自出海", prose="灯塔在远处亮了一下。",
    )


def test_export_markdown(client):
    c, repo = client
    _seed_novel(repo)
    resp = c.get("/api/projects/novel_p/export?format=md")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    text = resp.text
    assert text.startswith("# 雾中旅人")
    assert "## 第1章 雾起" in text
    assert "> 开场" in text
    assert "雾把码头吞了一半。" in text
    assert "## 第2章 灯塔" in text
    # 未归属章节场景归入末尾
    assert "## 未归属场景" in text
    assert "灯塔在远处亮了一下。" in text
    # 章节内顺序：scene_1 在 scene_2 前
    assert text.index("雾把码头") < text.index("她擦着杯子")


def test_export_txt(client):
    c, repo = client
    _seed_novel(repo)
    resp = c.get("/api/projects/novel_p/export?format=txt")
    assert resp.status_code == 200
    text = resp.text
    assert text.startswith("雾中旅人")
    assert "# 雾中旅人" not in text
    assert "===== 第1章 雾起 =====" in text
    assert "【场景 scene_1】" in text


def test_export_404(client):
    c, _ = client
    assert c.get("/api/projects/nope/export").status_code == 404


# ============================================================
# 项目指标
# ============================================================

def test_metrics_aggregation(client):
    c, repo = client
    repo.create_scene(
        "scene_1", "novel_p", brief="b1", prose="p1",
        quality_score=0.9, duration_ms=1000,
        model_usage={"director": "deepseek.v4pro", "prose": "claude.sonnet"},
    )
    repo.create_scene(
        "scene_2", "novel_p", brief="b2", prose="p2",
        quality_score=0.7, duration_ms=3000,
        model_usage={"director": "deepseek.v4pro"},
    )
    resp = c.get("/api/projects/novel_p/metrics")
    assert resp.status_code == 200
    m = resp.json()
    assert m["scene_count"] == 2
    assert m["avg_quality_score"] == pytest.approx(0.8)
    assert m["total_duration_ms"] == 4000
    assert m["avg_duration_ms"] == 2000.0
    assert m["model_calls"] == {"deepseek.v4pro": 2, "claude.sonnet": 1}
    assert m["agent_calls"]["director"] == 2
    assert len(m["scenes"]) == 2


def test_metrics_empty_project(client):
    c, _ = client
    resp = c.get("/api/projects/novel_p/metrics")
    assert resp.status_code == 200
    m = resp.json()
    assert m["scene_count"] == 0
    assert m["avg_quality_score"] is None


# ============================================================
# 配置导出 / 导入 / 跨项目复制
# ============================================================

def test_config_export_contains_seeded_agents(client):
    c, _ = client
    resp = c.get("/api/projects/novel_p/config/export")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == "novel_p"
    keys = {a["key"] for a in body["agents"]}
    # YAML 种子应包含导演等核心 Agent
    assert "director" in keys
    assert body["tasks"], "种子任务不应为空"
    # 导出快照不含库内字段
    assert "project_id" not in body["agents"][0]
    assert "crew" not in body["agents"][0]


def test_config_import_merge_and_overwrite(client):
    c, repo = client
    custom_agent = {
        "key": "critic", "role": "文风批评家",
        "goal": "挑陈词滥调", "backstory": "苛刻的文学编辑",
    }
    custom_task = {
        "key": "style_review", "description": "审查文风",
        "expected_output": "问题清单", "agent_key": "critic",
    }
    # merge：追加，不影响种子
    resp = c.post(
        "/api/projects/novel_p/config/import",
        json={"agents": [custom_agent], "tasks": [custom_task], "mode": "merge"},
    )
    assert resp.status_code == 200
    keys = {a["key"] for a in repo.list_agents("novel_p")}
    assert {"director", "critic"} <= keys

    # overwrite：清空后只剩导入内容
    resp = c.post(
        "/api/projects/novel_p/config/import",
        json={"agents": [custom_agent], "tasks": [custom_task],
              "mode": "overwrite"},
    )
    assert resp.status_code == 200
    assert {a["key"] for a in repo.list_agents("novel_p")} == {"critic"}
    assert {t["key"] for t in repo.list_tasks("novel_p")} == {"style_review"}


def test_config_import_invalid_422(client):
    c, _ = client
    resp = c.post(
        "/api/projects/novel_p/config/import",
        json={"agents": [{"key": "broken"}], "tasks": []},
    )
    assert resp.status_code == 422


def test_config_import_overwrite_empty_agents_422(client):
    """仓储约定项目零 Agent 时自动重播种，overwrite 不允许空 Agent 列表"""
    c, _ = client
    resp = c.post(
        "/api/projects/novel_p/config/import",
        json={"agents": [], "tasks": [], "mode": "overwrite"},
    )
    assert resp.status_code == 422


def test_config_copy_between_projects(client):
    c, repo = client
    repo.create_project("novel_q", "另一个项目", "wuxia")
    # 在源项目里放一个自定义 Agent
    repo.upsert_agent(
        "critic", project_id="novel_p",
        role="文风批评家", goal="挑错", backstory="编辑",
    )
    resp = c.post(
        "/api/projects/novel_q/config/copy_from",
        json={"source_project_id": "novel_p", "mode": "overwrite"},
    )
    assert resp.status_code == 200
    keys_src = {a["key"] for a in repo.list_agents("novel_p")}
    keys_dst = {a["key"] for a in repo.list_agents("novel_q")}
    assert keys_src == keys_dst
    assert "critic" in keys_dst


def test_config_copy_same_project_400(client):
    c, _ = client
    resp = c.post(
        "/api/projects/novel_p/config/copy_from",
        json={"source_project_id": "novel_p"},
    )
    assert resp.status_code == 400
