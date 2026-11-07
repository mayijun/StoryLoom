"""M0 API 端点测试（直接调用路由函数，不启动 HTTP 服务）"""

import asyncio

import pytest

from storyloom.api.schemas import (
    ExtensionResolveRequest,
    MemoryPatchRequest,
    ModeSwitchRequest,
    SaveCreateRequest,
    TurnRequest,
)
from storyloom.db import get_repository, reset_engines, reset_repositories
from storyloom.saves.service import SaveService


@pytest.fixture
def apis(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STORYLOOM_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}"
    )
    reset_repositories()
    reset_engines()

    from storyloom.api.engine import engine
    from storyloom.api.routers import extensions, game, memory

    engine._project_runtime.clear()
    engine.game_states.clear()
    engine.game_memories.clear()
    engine.last_turns.clear()
    engine.save_service = SaveService(root=str(tmp_path / "saves"))

    repo = get_repository()
    repo.create_project("m0api", "M0 API", "film_narrative")
    repo.upsert_character(
        "m0api", "玩家", "primary", "冷静", "查明真相", "秘密身份"
    )
    repo.upsert_character(
        "m0api", "侍卫长", "secondary", "忠诚", "保护", "认识父亲"
    )
    repo.upsert_location("m0api", "旅店", "潮湿")
    repo.upsert_location("m0api", "码头", "有雾")

    yield game, memory, extensions

    reset_repositories()
    reset_engines()


def test_game_turn_and_state(apis):
    game, _, _ = apis
    result = asyncio.run(
        game.play_turn(
            "m0api",
            TurnRequest(instance_id="i1", text="观察四周"),
        )
    )
    assert result["status"] == "ok"
    assert result["state"]["turn"] == 1
    assert result["scene"]["directives"]

    state = asyncio.run(game.get_state("m0api", instance_id="i1"))
    assert state["state"]["project_id"] == "m0api"
    assert state["memory"]["backend"] == "fts"


def test_game_saves_roundtrip(apis):
    game, _, _ = apis
    asyncio.run(
        game.play_turn("m0api", TurnRequest(instance_id="i1", text="观察四周"))
    )
    saved = asyncio.run(
        game.create_save("m0api", SaveCreateRequest(instance_id="i1", label="测试"))
    )
    listed = asyncio.run(game.list_saves("m0api"))
    assert [item["save_id"] for item in listed["saves"]] == [saved["save_id"]]

    loaded = asyncio.run(
        game.load_save("m0api", saved["save_id"], instance_id="i1")
    )
    assert loaded["text"] == saved["text"]
    assert loaded["world_state"]["turn"] == 1


def test_mode_switch_endpoint(apis):
    game, _, _ = apis
    result = asyncio.run(
        game.switch_mode(
            "m0api", ModeSwitchRequest(instance_id="i1", mode="director")
        )
    )
    assert result["mode"] == "director"
    assert result["checkpoint_id"]


def test_memory_get_and_patch_backend(apis):
    _, memory, _ = apis
    overview = asyncio.run(memory.get_memory("m0api"))
    assert overview["backend"] == "fts"
    assert "counts" in overview

    patched = asyncio.run(
        memory.patch_memory("m0api", MemoryPatchRequest(backend="hybrid"))
    )
    assert patched["backend"] == "hybrid"


def test_extensions_resolve_endpoint(apis):
    _, _, extensions = apis
    resolved = asyncio.run(
        extensions.resolve_extensions(
            ExtensionResolveRequest(instance_id="i1")
        )
    )
    assert resolved["instance_id"] == "i1"
    assert any(item["id"] == "map_xianxia" for item in resolved["mods"])


def test_provider_api_keys_injected_in_memory(apis):
    """bootstrap 传入的 Key 只注入运行时内存注册表"""
    game, _, _ = apis
    from storyloom.api.engine import engine

    asyncio.run(
        game.play_turn(
            "m0api",
            TurnRequest(
                instance_id="i1",
                text="观察四周",
                provider_api_keys={"deepseek": "sk-runtime-only"},
            ),
        )
    )
    assert engine.registry.get("deepseek.flash").api_key == "sk-runtime-only"
    assert "sk-runtime-only" not in str(
        engine.get_available_models()
    )


def test_runtime_v1_routes_registered(apis):
    """版本化入口可用，旧端点保留"""
    from fastapi.testclient import TestClient

    from storyloom.api.main import app

    with TestClient(app) as client:
        turn = client.post(
            "/runtime/v1/m0api/turn",
            json={"instance_id": "v1", "text": "观察四周"},
        )
        assert turn.status_code == 200, turn.text
        assert turn.json()["state"]["turn"] == 1

        state = client.get(
            "/runtime/v1/m0api/state", params={"instance_id": "v1"}
        )
        assert state.status_code == 200

        # 旧端点保留
        legacy = client.post(
            "/game/m0api/turn",
            json={"instance_id": "legacy", "text": "观察四周"},
        )
        assert legacy.status_code == 200
