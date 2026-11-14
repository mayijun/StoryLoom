"""记忆 API 测试（直接调用路由函数，不启动 HTTP 服务）。"""

import asyncio

from storyloom.api.schemas import MemoryPatchRequest


def test_memory_get_and_patch_backend(apis):
    _, memory, _ = apis
    overview = asyncio.run(memory.get_memory("api_demo"))
    assert overview["backend"] == "fts"
    assert "counts" in overview

    patched = asyncio.run(
        memory.patch_memory("api_demo", MemoryPatchRequest(backend="hybrid"))
    )
    assert patched["backend"] == "hybrid"


def test_compression_provider_selects_role(apis, monkeypatch):
    from storyloom.api.engine import engine
    from storyloom.memory import MemorySettings
    from storyloom.memory.models import (
        CharacterAsset,
        LocationAsset,
        NovelProject,
    )

    project = NovelProject(
        project_id="api_demo",
        title="API Demo",
        style="film_narrative",
        characters=[
            CharacterAsset(
                name="玩家",
                importance_tier="primary",
                persona="冷静",
                motivation="查明真相",
            ),
            CharacterAsset(
                name="侍卫长",
                importance_tier="secondary",
                persona="忠诚",
                motivation="保护",
            ),
        ],
        locations=[LocationAsset(name="旅店", description="潮湿")],
    )
    monkeypatch.setattr(
        engine, "_get_or_load_project", lambda project_id: project
    )

    def use(provider: str) -> None:
        settings = MemorySettings(tiers=[], compression_provider=provider)
        monkeypatch.setattr(
            engine, "_memory_settings_for", lambda project_id: settings
        )

    use("dedicated")
    assert engine._compression_role("api_demo", ["玩家"]) == "memory"

    use("director")
    assert engine._compression_role("api_demo", ["玩家"]) == "director"

    use("character")
    assert engine._compression_role("api_demo", ["玩家"]) == "protagonist"
    assert engine._compression_role("api_demo", ["侍卫长"]) == "ensemble"
    assert (
        engine._compression_role("api_demo", ["玩家", "侍卫长"])
        == "ensemble"
    )
    assert engine._compression_role("api_demo", ["all"]) == "director"
    assert engine._compression_role("api_demo", ["crowd"]) == "director"
    assert engine._compression_role("api_demo", []) == "director"
