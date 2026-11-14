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
from storyloom.memory import MemorySettings
from storyloom.memory.checkpoint import SaveService


def _fake_prose(prompt: str, state) -> str:
    """伪装 prose 模型：原样返回 prompt 里已裁决的「事实」，不访问网络。"""
    for line in prompt.splitlines():
        if line.startswith("事实："):
            return line[len("事实："):]
    return ""


async def _fake_crew_run(self, agent, prompt, timeout_s=60.0):
    """伪装统一 JSON Agent：裁决放行、正文为空、无一致性问题。"""
    return '{"decision": "allow", "prose": "", "choices": [], "issues": []}'


@pytest.fixture
def apis(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STORYLOOM_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}"
    )
    reset_repositories()
    reset_engines()

    from storyloom.api.engine import engine
    from storyloom.api.routers import extensions, game, memory
    from storyloom.crews.scene_crew.crew import SceneCrew

    # 游戏回合的叙述润色改为假模型返回，避免真实 LLM 调用导致超时
    monkeypatch.setattr(engine, "_game_prose_fn", _fake_prose)
    # 记忆压缩同样走确定性兜底
    monkeypatch.setattr(
        engine, "_memory_compress_fn",
        lambda project_id, prompt, scope=None: "",
    )
    # Crew 叙事增强层整体关闭（一致性 / 意外 / 伏笔 / 导演 / 润色）
    # NarrativeEngine._kickoff 优先走 crew.run_agent，直接 patch SceneCrew 即可
    monkeypatch.setattr(SceneCrew, "run_agent", _fake_crew_run)
    engine._project_runtime.clear()
    engine.memories.clear()
    engine.game_states.clear()
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


def test_freeform_api_text_does_not_require_intent(apis):
    """任意原文都可进入游戏，不再经过结构化 intent 或动作白名单。"""
    result = asyncio.run(
        apis[0].play_turn(
            "m0api",
            TurnRequest(
                instance_id="i1",
                text="把签到契折成纸飞机，从窗口放飞",
            ),
        )
    )
    assert result["status"] == "ok"
    assert result["state"]["turn"] == 1
    assert result["state_delta"]["events"][-1]["summary"] == (
        "把签到契折成纸飞机，从窗口放飞"
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


def test_turn_advances_arc_and_returns_frame(apis):
    game, _, _ = apis
    before = asyncio.run(game.get_state("m0api", instance_id="i1"))
    result = asyncio.run(
        game.play_turn("m0api", TurnRequest(instance_id="i1", text="观察四周"))
    )
    assert result["status"] == "ok"
    assert result["frame"] is not None
    assert result["frame"]["phase"] == "setup"
    assert result["state"]["arc"]["beats_remaining"] == (
        before["state"]["arc"]["beats_remaining"] - 1
    )


def test_turn_mode_switch_writes_checkpoint(apis):
    game, _, _ = apis
    result = asyncio.run(
        game.play_turn(
            "m0api",
            TurnRequest(
                instance_id="i1",
                text="观察四周",
                mode="director",
                switch_mode_to="director",
            ),
        )
    )
    assert result["state"]["mode"] == "director"
    assert result["state"]["flags"]["last_checkpoint_id"]


def test_turn_applies_overrides_before_narrative(apis):
    game, _, _ = apis
    result = asyncio.run(
        game.play_turn(
            "m0api",
            TurnRequest(
                instance_id="i1",
                text="观察四周",
                overrides=[
                    {
                        "target": "侍卫长",
                        "field": "emotion",
                        "after": "紧张",
                        "reason": "测试改写",
                    }
                ],
            ),
        )
    )
    assert result["state"]["characters"]["侍卫长"]["emotion"] == "紧张"
    assert result["state"]["overrides"]


def test_turn_timeout_returns_timeout_status(apis, monkeypatch):
    game, _, _ = apis
    from storyloom.engine.narrative import NarrativeEngine

    async def _slow_play_turn(self, **kwargs):
        await asyncio.sleep(0.2)

    monkeypatch.setattr(NarrativeEngine, "play_turn", _slow_play_turn)
    result = asyncio.run(
        game.play_turn(
            "m0api",
            TurnRequest(instance_id="i1", text="观察四周", max_duration_ms=10),
        )
    )
    assert result["status"] == "timeout"


def test_turn_quota_exceeded(apis):
    game, _, _ = apis
    result = asyncio.run(
        game.play_turn(
            "m0api",
            TurnRequest(instance_id="i1", text="观察四周", max_turns=0),
        )
    )
    assert result["status"] == "quota_exceeded"


def test_compression_provider_selects_role(apis, monkeypatch):
    from storyloom.api.engine import StoryEngine, engine

    def _settings(provider):
        monkeypatch.setattr(
            engine,
            "_memory_settings_for",
            lambda project_id: MemorySettings(
                compression_provider=provider
            ),
        )

    _settings("dedicated")
    assert engine._compression_role("m0api", ["玩家"]) == "memory"
    _settings("director")
    assert engine._compression_role("m0api", ["玩家"]) == "director"
    _settings("character")
    assert engine._compression_role("m0api", ["玩家"]) == "protagonist"
    assert engine._compression_role("m0api", ["侍卫长"]) == "ensemble"
    assert engine._compression_role("m0api", ["玩家", "侍卫长"]) == "ensemble"
    assert engine._compression_role("m0api", ["all"]) == "director"
    assert engine._compression_role("m0api", []) == "director"

    roles = []

    class StubLLM:
        def call(self, messages):
            return "压缩结果"

    class StubRouter:
        def get_llm_for_role(self, role):
            roles.append(role)
            return StubLLM(), None

    monkeypatch.setattr(engine, "router", StubRouter())
    monkeypatch.setattr(
        engine, "_compression_role", lambda project_id, scope: "protagonist"
    )
    # apis fixture 把实例方法替换成了空串；这里直接测原始类方法。
    assert (
        StoryEngine._memory_compress_fn(
            engine, "m0api", "prompt", ["玩家"]
        )
        == "压缩结果"
    )
    assert roles == ["protagonist"]
