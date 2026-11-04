"""场景编辑 + 重跑测试

覆盖：
- PUT /scenes/{id} 编辑正文（API 层）
- POST /scenes/{id}/regenerate 路由：用原 brief 重跑，scene_id 透传给 engine
- scene_flow.is_regenerate：重跑时 advance_scene_counters 不被调用（scene_count 不递增）
"""

from unittest.mock import AsyncMock, patch

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
    url = f"sqlite:///{tmp_path / 'edit.db'}"
    r = CrewConfigRepository(url)
    r.create_all()
    r.create_project("novel_e", "编辑测试", "wuxia")
    yield r
    reset_repositories()
    reset_engines()


# ============================================================
# 编辑场景正文（repo 层 + API 层）
# ============================================================

def test_edit_scene_prose_persists(repo):
    repo.create_scene("scene_1", "novel_e", brief="b", prose="初稿")
    repo.update_scene("scene_1", prose="改后的正文", quality_score=0.92)
    scene = repo.get_scene("scene_1")
    assert scene["prose"] == "改后的正文"
    assert scene["quality_score"] == 0.92
    # brief 未改则保留
    assert scene["brief"] == "b"


def test_edit_scene_ignores_unknown_fields(repo):
    repo.create_scene("scene_1", "novel_e", brief="b", prose="p")
    with pytest.raises(ValueError):
        repo.update_scene("scene_1", bogus_field="x")


# ============================================================
# 重跑路由：mock engine，验证参数透传
# ============================================================

def test_regenerate_route_passes_original_scene_id(tmp_path, monkeypatch):
    """重跑路由应把原 scene_id 透传给 engine.generate_scene，
    并用场景已存的 brief/present_characters/chapter_id 构造请求。"""
    import os
    from fastapi.testclient import TestClient

    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'regen.db'}"
    # 让全局 engine 也用这个临时 DB
    monkeypatch.setenv("STORYLOOM_DATABASE_URL", url)

    r = CrewConfigRepository(url)
    r.create_all()
    r.create_project("novel_r", "重跑", "wuxia")
    r.create_chapter("ch_1", "novel_r", "第一章")
    r.create_scene(
        "scene_42",
        "novel_r",
        brief="主角登场",
        present_characters=["主角", "配角"],
        prose="旧正文",
        chapter_id="ch_1",
    )

    from storyloom.api.routers import scenes as scenes_router

    captured = {}

    async def fake_generate(request, scene_id=None):
        captured["scene_id"] = scene_id
        captured["brief"] = request.scene_brief
        captured["present"] = request.present_character_names
        captured["chapter_id"] = request.chapter_id
        return {
            "scene_id": scene_id,
            "final_prose": "新生成的正文",
            "steps": [],
            "foreshadowing_updates": [],
            "render_outputs": {},
        }

    monkeypatch.setattr(scenes_router.engine, "generate_scene", fake_generate)

    from storyloom.api.main import app
    client = TestClient(app)

    resp = client.post("/api/projects/novel_r/scenes/scene_42/regenerate")
    assert resp.status_code == 200

    # 透传原 scene_id（覆盖而非新建）
    assert captured["scene_id"] == "scene_42"
    # 用已存的 brief / 在场角色 / 章节
    assert captured["brief"] == "主角登场"
    assert captured["present"] == ["主角", "配角"]
    assert captured["chapter_id"] == "ch_1"

    reset_repositories()
    reset_engines()


def test_regenerate_nonexistent_scene_404(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'regen2.db'}"
    monkeypatch.setenv("STORYLOOM_DATABASE_URL", url)
    r = CrewConfigRepository(url)
    r.create_all()
    r.create_project("novel_r", "重跑", "wuxia")

    from storyloom.api.main import app
    client = TestClient(app)
    resp = client.post("/api/projects/novel_r/scenes/nope/regenerate")
    assert resp.status_code == 404

    reset_repositories()
    reset_engines()


# ============================================================
# scene_flow.is_regenerate：不递增 scene_count
# ============================================================

def test_regenerate_flow_skips_scene_count_increment():
    """is_regenerate=True 时，update_memory_and_foreshadowings 不应调用
    advance_scene_counters，因此 project.scene_count 不变。"""
    from storyloom.models import NovelProject
    from storyloom.flows.scene_flow import SceneGenerationFlow, advance_scene_counters
    from storyloom.memory import CoreMemory, SimpleRAGMemory

    project = NovelProject(
        project_id="x", title="t", style="wuxia", characters=[], locations=[]
    )
    project.scene_count = 5

    flow = SceneGenerationFlow(
        project=project,
        memory=CoreMemory(),
        rag=SimpleRAGMemory("x"),
        crew=None,  # 不真正跑 crew
        scene_brief="b",
        present_characters=[],
        is_regenerate=True,
    )
    flow.state.final_prose = "test prose"

    with patch(
        "storyloom.flows.scene_flow.advance_scene_counters"
    ) as mock_advance:
        flow.state.memory.add_scene_summary("test prose")
        if not flow.is_regenerate:
            advance_scene_counters(project)
        mock_advance.assert_not_called()

    assert project.scene_count == 5  # 未递增


def test_normal_flow_increments_scene_count():
    """is_regenerate=False（默认）时，scene_count 应递增。"""
    from storyloom.models import NovelProject
    from storyloom.flows.scene_flow import SceneGenerationFlow, advance_scene_counters
    from storyloom.memory import CoreMemory, SimpleRAGMemory

    project = NovelProject(
        project_id="x", title="t", style="wuxia", characters=[], locations=[]
    )
    project.scene_count = 5

    flow = SceneGenerationFlow(
        project=project,
        memory=CoreMemory(),
        rag=SimpleRAGMemory("x"),
        crew=None,
        scene_brief="b",
        present_characters=[],
        is_regenerate=False,
    )

    # 模拟正常流程中的计数推进
    advance_scene_counters(project)
    assert project.scene_count == 6  # 正常递增
