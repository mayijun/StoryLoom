"""M0 双模式纵切验收测试（无需 API Key）

覆盖 MVP.md §2.5 的 A1~A5、A8~A15。
"""

import asyncio

import pytest

from storyloom.db import CrewConfigRepository, reset_engines, reset_repositories
from storyloom.extensions.host import ExtensionHost, ExtensionRegistry
from storyloom.extensions.manifest import ManifestError, discover, validate_manifest
from storyloom.flows.turn_flow import TurnBoot, TurnLoop
from storyloom.memory import (
    LayeredMemory,
    LexicalBackend,
    MemoryIndexer,
    VectorBackend,
)
from storyloom.memory.models import CharacterAsset, LocationAsset, NovelProject
from storyloom.crews.scene_crew.packet import (
    AgentPacket,
    compose_scene,
    packet_to_result,
    parse_agent_packet,
)
from storyloom.memory.checkpoint import SaveService, state_from_save
from storyloom.memory.state import (
    ActionProposal,
    Fact,
    FactOverride,
    StageDirective,
    StageScene,
    WorldState,
)


@pytest.fixture
def repo(tmp_path):
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'm0.db'}"
    yield CrewConfigRepository(url)
    reset_repositories()
    reset_engines()


@pytest.fixture
def project():
    return NovelProject(
        project_id="world_demo",
        title="雾港疑云",
        style="film_narrative",
        characters=[
            CharacterAsset(
                name="玩家",
                importance_tier="primary",
                persona="刚回到雾港的陌生人",
                motivation="查清父亲失踪的真相",
                secrets="你的真实身份是王室的私生子。",
            ),
            CharacterAsset(
                name="国王",
                importance_tier="primary",
                persona="声音不高",
                motivation="守住王位",
                secrets="父亲失踪与你有关。",
            ),
            CharacterAsset(
                name="侍卫长",
                importance_tier="secondary",
                persona="甲胄不离身",
                motivation="保护国王",
                secrets="他认识你的父亲。",
            ),
            CharacterAsset(
                name="旅店老板",
                importance_tier="background",
                persona="一边擦杯子一边观察客人",
                motivation="把小店开下去",
                secrets="航海图是他藏起来的。",
            ),
        ],
        locations=[
            LocationAsset(name="雾港旅店", description="潮湿的木楼"),
            LocationAsset(name="码头", description="缆绳与鱼腥味"),
            LocationAsset(name="王宫", description="白色石阶"),
            LocationAsset(name="地牢", description="石壁渗水"),
        ],
    )


@pytest.fixture
def world(project):
    state = WorldState.from_project(project)
    state.locations["雾港旅店"].exits = {"码头": 10}
    state.locations["码头"].exits = {"雾港旅店": 10, "王宫": 20}
    state.locations["王宫"].exits = {"码头": 20, "地牢": 5}
    state.locations["地牢"].exits = {"王宫": 5}
    return state


# ---------------- A1 / A2：LLM 裁决 JSON ----------------
# 裁决已并入导演 Agent：LLM 输出 decision / state / available，
# packet_to_result 把它转成可执行的 AdjudicationResult。


def test_a1_llm_packet_can_express_guard_intercept(world):
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


def test_a2_llm_packet_can_reject_teleport_with_available_locations(world):
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


# ---------------- A3：信息隔离 ----------------


def test_a3_fact_visibility_filters_by_known_by(world):
    fact = Fact(
        subject="玩家",
        predicate="经历",
        object="曾在北境见过国王",
        known_by={"玩家", "gm"},
    )
    world.facts[fact.id] = fact

    player_view = world.view("玩家")
    guard_view = world.view("侍卫长")
    assert any(f["id"] == fact.id for f in player_view["facts"])
    assert all(f["id"] != fact.id for f in guard_view["facts"])


# ---------------- A3b / L3a：_world_context 信息迷雾修复 ----------------


def test_a3b_world_context_fog_hides_unseeable(project, world):
    """_world_context 对非全知 actor 只泄露 view() 可见内容。"""
    # 布置：玩家在雾港旅店，国王和侍卫长在王宫
    world.characters["玩家"].location = "雾港旅店"
    world.characters["国王"].location = "王宫"
    world.characters["侍卫长"].location = "王宫"
    # GM 内部标记（不该进 world_book）
    world.flags["_gm_secret_layoff"] = True
    # NPC-NPC 关系（玩家不该知道）
    world.relationships["国王|侍卫长"] = 10
    world.relationships["玩家|旅店老板"] = 3
    # 玩家不知道的 fact
    hidden = Fact(
        subject="国王",
        predicate="秘密",
        object="准备逃亡",
        known_by={"国王", "gm"},
    )
    world.facts[hidden.id] = hidden

    loop = TurnLoop(project)
    book = loop._world_context(world, "玩家")

    # —— 应该隐藏 ——
    assert "王宫" not in book  # 未探索地点
    assert "地牢" not in book
    assert "国王" not in book.split("在场角色")[1].split("已知事实")[0] if "在场角色" in book else True  # 在场角色不含国王
    assert "_gm_secret_layoff" not in book  # GM flags
    assert "国王|侍卫长" not in book  # NPC-NPC 关系
    assert "准备逃亡" not in book  # hidden fact

    # —— 应该包含 ——
    assert "雾港旅店" in book
    assert "玩家" in book
    assert "玩家|旅店老板" in book  # 含玩家的关系
    assert "雾港旅店" in book


def test_a3b_world_context_gm_sees_everything(project, world):
    """GM actor 调用时 view() 自动全知，world_book 应包含所有信息。"""
    world.characters["玩家"].location = "雾港旅店"
    world.characters["国王"].location = "王宫"
    world.relationships["国王|侍卫长"] = 10
    hidden = Fact(
        subject="国王",
        predicate="秘密",
        object="准备逃亡",
        known_by={"国王", "gm"},
    )
    world.facts[hidden.id] = hidden

    loop = TurnLoop(project)
    book = loop._world_context(world, "gm")

    assert "王宫" in book
    assert "地牢" in book
    assert "国王" in book
    assert "国王|侍卫长" in book
    assert "准备逃亡" in book


# ---------------- A4：存档回放 ----------------


def test_a4_save_load_replay_is_identical(tmp_path, world):
    scene = StageScene(
        directives=[StageDirective(kind="say", params={"text": "雾从海面压下来。"})],
        text="雾从海面压下来。",
        choices=[{"index": 0, "label": "前往码头"}],
    )
    service = SaveService(root=str(tmp_path / "saves"))
    record = service.save("world_demo", world, scene, label="测试存档")

    loaded = service.load("world_demo", record.save_id)
    replayed = service.replay("world_demo", record.save_id)

    assert replayed.text == scene.text
    assert replayed.directives == [
        d.model_dump(mode="json") for d in scene.directives
    ]
    assert state_from_save(loaded).model_dump() == world.model_dump()
    assert [s.save_id for s in service.list("world_demo")] == [record.save_id]


# ---------------- A5：扩展 manifest ----------------


def test_a5_demo_manifests_resolve_and_travel_override(world):
    # 模板内嵌的扩展由 ExtensionRegistry 启动时自动加载，不再依赖 examples/ YAML
    registry = ExtensionRegistry()
    host = registry.for_instance("inst-1")
    resolved = host.resolve()
    assert any(item["id"] == "skill_xianxia" for item in resolved["skills"])
    assert any(item["id"] == "map_xianxia" for item in resolved["mods"])
    assert resolved["travel_overrides"]["演武场->杂役院"] == 8
    assert all(tool["read_only"] for tool in resolved["tools"])

    mapped = host.apply_map(world)
    assert "演武场" in mapped.locations
    assert mapped.locations["演武场"].exits["杂役院"] == 8
    # 旅行耗时仍由 mod 注入世界；是否移动由导演 Agent 裁决。
    assert host.travel_overrides()["演武场->杂役院"] == 8


def test_a5_bad_manifest_rejected():
    with pytest.raises(ManifestError):
        validate_manifest(
            {
                "id": "bad_mod",
                "kind": "mod",
                "api_version": 1,
                "contributes": {
                    "rules": [
                        {"id": "evil", "handler": "os.system"}
                    ]
                },
            }
        )
    with pytest.raises(ManifestError):
        validate_manifest(
            {
                "id": "leaky_mod",
                "kind": "mod",
                "api_version": 1,
                "contributes": {
                    "tools": [
                        {"id": "leak", "read_only": False, "handler": "builtin.map.route"}
                    ]
                },
            }
        )


# ---------------- A8：导演改写审计与回滚 ----------------


def test_a8_override_audit_and_rollback(world):
    override = FactOverride(
        target="国王",
        field="emotion",
        after="恐惧",
        reason="剧情需要",
    )
    new_world, record = world.apply_override(override, snapshot_id="snap_1")
    assert new_world.characters["国王"].emotion == "恐惧"
    assert record.before == "平静"
    assert new_world.overrides[0]["after"] == "恐惧"
    assert new_world.flags["needs_review:国王"] is True

    rolled = new_world.rollback_override(record.override_id)
    assert rolled.characters["国王"].emotion == "平静"
    assert rolled.overrides[0]["rolled_back"] is True


# ---------------- A9：NPC 自主 ----------------


def test_a9_idle_three_turns_triggers_npc_event(project, world):
    world.characters["玩家"].location = "王宫"
    world.characters["国王"].location = "王宫"
    world.characters["侍卫长"].location = "王宫"

    loop = TurnLoop(project)
    result = asyncio.run(
        loop.run(
            TurnBoot(
                project_id="world_demo",
                world_state=world,
                wait=True,
                idle_turns=3,
            )
        )
    )
    assert result.status == "ok"
    assert result.state_delta.events
    assert all(e.actor != "玩家" for e in result.state_delta.events)


# ---------------- A10：模式切换 checkpoint ----------------


def test_a10_mode_switch_writes_checkpoint(world):
    new_state = world.switch_mode("director", checkpoint_id="save_switch")
    assert new_state.mode == "director"
    assert new_state.flags["force_director_frame"] is True
    assert new_state.flags["last_checkpoint_id"] == "save_switch"
    assert world.mode == "game"  # 原状态不被原地修改


# ---------------- A11 / A12 / A13 / A14 / A15：分层记忆 ----------------


def test_a11_short_term_compress_and_restart_recovery(repo):
    memory = LayeredMemory("p_a11", repo=repo)
    for index in range(7):
        memory.add_scene(
            scene_index=index,
            prose=f"第{index}个场景：雾从海面压下来，航海图被打湿了。" * 3,
            brief=f"场景 {index}",
        )
    counts = memory.counts()
    assert counts["short_term"] <= 6
    assert counts["long_term"] >= 1

    restored = LayeredMemory("p_a11", repo=repo)
    assert restored.counts() == counts
    assert restored.has_scene_memory()


def test_a12_demote_and_reheat(repo):
    memory = LayeredMemory("p_a12", repo=repo)
    item = memory.add_archive_item(
        "cold_memory", "一段无人再提的旧事", scene_index=0, importance=0.1
    )
    item.tier = "long_term"
    item.last_hit_scene = 0
    memory._put(item)

    demoted = memory.evaluate_demotion(10)
    assert [i.id for i in demoted] == ["cold_memory"]
    assert memory.items["cold_memory"].tier == "archive"
    assert memory.items["cold_memory"].source == "demoted"

    memory.retrieve("旧事", current_scene=11)
    memory.retrieve("旧事", current_scene=12)
    assert memory.items["cold_memory"].tier == "long_term"
    assert memory.items["cold_memory"].source == "reheated"


def test_a13_backfill_scenes_and_chinese_proper_noun(repo):
    memory = LayeredMemory("p_a13", repo=repo)
    count = MemoryIndexer(memory).backfill(
        scenes=[
            {
                "scene_id": "s1",
                "brief": "旅店墙上",
                "prose": "墙上挂着一张被海雾打湿的航海图。",
            }
        ]
    )
    assert count >= 1
    hits = memory.retrieve("航海图")
    assert [item.id for item in hits] == ["scene:s1"]


def test_a14_backends_switch_and_degrade(repo):
    vector = LayeredMemory("p_a14", repo=repo, backend="vector")
    vector.add_archive_item("d1", "航海图", scene_index=1)
    assert vector.backend_name == "vector"
    assert vector.retrieve("航海图") == []  # 无 embedding 自动降级为空

    hybrid = LayeredMemory("p_a14h", repo=repo, backend="hybrid")
    hybrid.add_archive_item("d1", "航海图", scene_index=1)
    assert [item.id for item in hybrid.retrieve("航海图")] == ["d1"]

    fts = LayeredMemory("p_a14f", repo=repo, backend="fts")
    fts.add_archive_item("d1", "航海图", scene_index=1)
    assert [item.id for item in fts.retrieve("航海图")] == ["d1"]


def test_a15_secrets_visibility(repo, project):
    memory = LayeredMemory("p_a15", repo=repo)
    MemoryIndexer(memory).backfill(
        scenes=[], characters=project.characters
    )
    assert memory.retrieve("私生子", viewer="国王") == []
    assert [i.id for i in memory.retrieve("私生子", viewer="玩家")] == [
        "secret:玩家"
    ]
    assert "私生子" not in memory.prompt_block(viewer="国王")


# ---------------- 自由输入与渲染 ----------------


def test_freeform_text_enters_narrative_pipeline_without_action_parser(
    project, world
):
    action = "把账单折成纸船，放进街角的积水里"
    loop = TurnLoop(project)
    result = asyncio.run(
        loop.run(
            TurnBoot(
                project_id="world_demo",
                world_state=world,
                text=action,
            )
        )
    )

    assert result.status == "ok"
    assert result.state.time_minutes == world.time_minutes + 1
    assert result.state_delta.events[-1].summary == action
    adjudication = next(
        item for item in result.log["trace"] if item["stage"] == "adjudicate"
    )
    assert adjudication["results"] == ["narrated"]


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


# ---------------- TurnLoop 配额与超时 ----------------


def test_timeout_returns_immediately(project, world):
    def slow_prose(prompt, state):
        import time

        time.sleep(0.3)
        return "慢"

    loop = TurnLoop(project, prose_fn=slow_prose)
    result = asyncio.run(
        loop.run(
            TurnBoot(
                project_id="world_demo",
                world_state=world,
                text="观察四周",
                max_duration_ms=50,
            )
        )
    )
    assert result.status == "timeout"


def test_quota_rejects_when_no_turns_left(project, world):
    loop = TurnLoop(project)
    result = asyncio.run(
        loop.run(
            TurnBoot(
                project_id="world_demo",
                world_state=world,
                max_turns=0,
            )
        )
    )
    assert result.status == "quota_exceeded"


# ---------------- 导演模式不回归 ----------------


def test_director_mode_turn_runs_without_touching_game_entry(project, world):
    loop = TurnLoop(project)
    result = asyncio.run(
        loop.run(
            TurnBoot(
                project_id="world_demo",
                mode="director",
                world_state=world,
                goal="让雾更浓，压住码头的灯光。",
                text="让雾更浓",
            )
        )
    )
    assert result.status == "ok"
    assert result.text
    assert result.state.mode == "director"
