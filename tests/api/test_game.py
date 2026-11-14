"""游戏回合与版本化运行时路由测试（直接调用路由函数，不启动 HTTP 服务）。"""

import asyncio

from storyloom.api.schemas import ModeSwitchRequest, SaveCreateRequest, TurnRequest


def test_game_turn_and_state(apis):
    game, _, _ = apis
    result = asyncio.run(
        game.play_turn(
            "api_demo",
            TurnRequest(instance_id="i1", text="观察四周"),
        )
    )
    assert result["status"] == "ok"
    assert result["state"]["turn"] == 1
    assert result["scene"]["directives"]

    state = asyncio.run(game.get_state("api_demo", instance_id="i1"))
    assert state["state"]["project_id"] == "api_demo"
    assert state["memory"]["backend"] == "fts"


def test_game_saves_roundtrip(apis):
    game, _, _ = apis
    asyncio.run(
        game.play_turn("api_demo", TurnRequest(instance_id="i1", text="观察四周"))
    )
    saved = asyncio.run(
        game.create_save(
            "api_demo", SaveCreateRequest(instance_id="i1", label="测试")
        )
    )
    listed = asyncio.run(game.list_saves("api_demo"))
    assert [item["save_id"] for item in listed["saves"]] == [saved["save_id"]]

    loaded = asyncio.run(
        game.load_save("api_demo", saved["save_id"], instance_id="i1")
    )
    assert loaded["text"] == saved["text"]
    assert loaded["world_state"]["turn"] == 1


def test_mode_switch_endpoint(apis):
    game, _, _ = apis
    result = asyncio.run(
        game.switch_mode(
            "api_demo", ModeSwitchRequest(instance_id="i1", mode="director")
        )
    )
    assert result["mode"] == "director"
    assert result["checkpoint_id"]


def test_freeform_api_text_does_not_require_intent(apis):
    """任意原文都可进入游戏，不再经过结构化 intent 或动作白名单。"""
    result = asyncio.run(
        apis[0].play_turn(
            "api_demo",
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
            "/runtime/v1/api_demo/turn",
            json={"instance_id": "v1", "text": "观察四周"},
        )
        assert turn.status_code == 200, turn.text
        assert turn.json()["state"]["turn"] == 1

        state = client.get(
            "/runtime/v1/api_demo/state", params={"instance_id": "v1"}
        )
        assert state.status_code == 200

        # 旧端点保留
        legacy = client.post(
            "/game/api_demo/turn",
            json={"instance_id": "legacy", "text": "观察四周"},
        )
        assert legacy.status_code == 200


def test_turn_advances_arc_and_returns_frame(apis):
    game, _, _ = apis
    before = asyncio.run(game.get_state("api_demo", instance_id="i1"))
    result = asyncio.run(
        game.play_turn("api_demo", TurnRequest(instance_id="i1", text="观察四周"))
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
            "api_demo",
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
            "api_demo",
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
            "api_demo",
            TurnRequest(instance_id="i1", text="观察四周", max_duration_ms=10),
        )
    )
    assert result["status"] == "timeout"


def test_turn_quota_exceeded(apis):
    game, _, _ = apis
    result = asyncio.run(
        game.play_turn(
            "api_demo",
            TurnRequest(instance_id="i1", text="观察四周", max_turns=0),
        )
    )
    assert result["status"] == "quota_exceeded"
