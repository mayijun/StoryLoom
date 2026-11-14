"""运行时引擎的配额、超时、Key 注入与压缩角色测试。"""

import asyncio

from storyloom.api.schemas import TurnRequest
from storyloom.engine.narrative import NarrativeEngine, TurnBoot
from storyloom.memory import MemorySettings


def test_timeout_returns_immediately(project, world, monkeypatch):
    """StoryEngine.play_turn 用 asyncio.wait_for 包住回合。"""
    from storyloom.api.engine import StoryEngine

    async def _slow(self, **kwargs):
        await asyncio.sleep(0.2)

    monkeypatch.setattr(NarrativeEngine, "play_turn", _slow)

    story = StoryEngine()
    story._project_runtime["world_demo"] = project
    story.game_states[("world_demo", "default")] = world

    result = asyncio.run(
        story.play_turn(
            "world_demo",
            TurnBoot(world_state=world, text="观察四周", max_duration_ms=10),
        )
    )
    assert result.status == "timeout"


def test_quota_rejects_when_no_turns_left(project, world):
    """StoryEngine.play_turn 的前置配额检查。"""
    from storyloom.api.engine import StoryEngine

    story = StoryEngine()
    story._project_runtime["world_demo"] = project
    story.game_states[("world_demo", "default")] = world

    result = asyncio.run(
        story.play_turn(
            "world_demo",
            TurnBoot(world_state=world, max_turns=0),
        )
    )
    assert result.status == "quota_exceeded"


def test_provider_api_keys_injected_in_memory(apis):
    """bootstrap 传入的 Key 只注入运行时内存注册表"""
    game, _, _ = apis
    from storyloom.api.engine import engine

    asyncio.run(
        game.play_turn(
            "api_demo",
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
    assert engine._compression_role("api_demo", ["玩家"]) == "memory"
    _settings("director")
    assert engine._compression_role("api_demo", ["玩家"]) == "director"
    _settings("character")
    assert engine._compression_role("api_demo", ["玩家"]) == "protagonist"
    assert engine._compression_role("api_demo", ["侍卫长"]) == "ensemble"
    assert engine._compression_role("api_demo", ["玩家", "侍卫长"]) == "ensemble"
    assert engine._compression_role("api_demo", ["all"]) == "director"
    assert engine._compression_role("api_demo", []) == "director"

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
            engine, "api_demo", "prompt", ["玩家"]
        )
        == "压缩结果"
    )
    assert roles == ["protagonist"]
