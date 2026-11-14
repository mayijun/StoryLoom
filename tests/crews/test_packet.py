"""场景 Crew 的 Agent JSON 包解析与舞台编排测试（无需 API Key）。"""

from storyloom.crews.scene_crew.packet import (
    compose_scene,
    packet_to_result,
    parse_agent_packet,
)


def test_packet_can_express_guard_intercept(world):
    world.characters["玩家"].location = "王宫"
    world.characters["国王"].location = "王宫"
    world.characters["侍卫长"].location = "王宫"
    before_time = world.time_minutes

    packet = parse_agent_packet(
        """{
          "decision": "reject",
          "narrative": "你刚拔出武器，侍卫长已经挡在国王身前。你被制服并押往地牢。",
          "reason": "护卫拦截",
          "state": {
            "time_delta": 5,
            "characters": {"玩家": {"location": "地牢", "emotion": "恐惧"}},
            "events": [
              {"kind": "attack", "actor": "玩家", "summary": "玩家袭击国王，被侍卫长制止"}
            ]
          }
        }"""
    )
    result = packet_to_result(packet)
    after = world.apply_delta(result.state_delta)

    assert result.success is False
    assert after.characters["玩家"].location == "地牢"
    assert after.characters["玩家"].emotion == "恐惧"
    assert after.time_minutes == before_time + 5
    assert any(e.kind == "attack" for e in after.events)


def test_packet_can_reject_teleport_with_available_locations(world):
    world.characters["玩家"].location = "雾港旅店"

    packet = parse_agent_packet(
        """{
          "decision": "reject",
          "narrative": "你无法凭空出现在王宫。",
          "reason": "不可达",
          "available": ["码头"]
        }"""
    )
    result = packet_to_result(packet)
    assert result.success is False
    assert "码头" in result.available
    assert "王宫" not in result.available


def test_agent_suggestions_render_as_free_text_choices(world):
    packet = parse_agent_packet(
        """{
          "prose": "旅店老板把一张潮湿的账单推到你面前。",
          "choices": [
            {"text": "和旅店老板聊聊账单上的数字", "hint": "可能获得新线索"},
            {"text": "观察账房的进出的人"},
            {"text": "把账单悄悄收进衣袋"},
            {"text": "和旅店老板聊聊账单上的数字", "hint": "重复项"}
          ]
        }"""
    )
    assert packet.prose == "旅店老板把一张潮湿的账单推到你面前。"
    assert len(packet.choices) == 3

    adjudication = packet_to_result(
        parse_agent_packet('{"decision": "allow", "narrative": "你环顾四周。"}')
    )
    after = world.apply_delta(adjudication.state_delta)
    scene = compose_scene(world, after, adjudication, packet=packet)

    assert scene.choices[0]["source"] == "agent"
    assert "action" not in scene.choices[0]
    assert scene.choices[0]["text"] == "和旅店老板聊聊账单上的数字"


def test_plain_prose_remains_compatible(world):
    packet = parse_agent_packet("门外的脚步声停了。")
    assert packet.prose == "门外的脚步声停了。"
    assert packet.choices == []

    adjudication = packet_to_result(
        parse_agent_packet('{"decision": "allow", "narrative": "门外的脚步声停了。"}')
    )
    scene = compose_scene(world, world, adjudication, packet=packet)
    assert scene.choices
    assert all(choice["source"] == "rules" for choice in scene.choices)


def test_scene_directives_are_json_serializable(world):
    world.characters["玩家"].location = "王宫"
    result = packet_to_result(
        parse_agent_packet('{"decision": "allow", "narrative": "你环顾四周。"}')
    )
    after = world.apply_delta(result.state_delta)
    scene = compose_scene(world, after, result)
    payload = scene.model_dump(mode="json")
    assert payload["directives"]
    assert any(d["kind"] == "choice" for d in payload["directives"])
    assert any(d["kind"] == "end" for d in payload["directives"])
