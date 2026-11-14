"""M0 双模式纵切验收测试（无需 API Key）

覆盖 MVP.md §2.5 的 A1~A5、A8~A15。
"""

import asyncio

import pytest

from storyloom.db import CrewConfigRepository, reset_engines, reset_repositories
from storyloom.engine.narrative import NarrativeEngine, TurnBoot
from storyloom.extensions.host import ExtensionHost, ExtensionRegistry
from storyloom.extensions.manifest import ManifestError, discover, validate_manifest
from storyloom.memory import (
    LayeredMemory,
    LexicalBackend,
    MemoryIndexer,
    VectorBackend,
)
from storyloom.memory.models import (
    CharacterAsset,
    Foreshadowing,
    LocationAsset,
    NovelProject,
)
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
            ),
            CharacterAsset(
                name="国王",
                importance_tier="primary",
                persona="声音不高",
                motivation="守住王位",
            ),
            CharacterAsset(
                name="侍卫长",
                importance_tier="secondary",
                persona="甲胄不离身",
                motivation="保护国王",
            ),
            CharacterAsset(
                name="旅店老板",
                importance_tier="background",
                persona="一边擦杯子一边观察客人",
                motivation="把小店开下去",
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


def test_a3_fact_visibility_filters_by_visible_to(world):
    fact = Fact(
        subject="玩家",
        predicate="经历",
        object="曾在北境见过国王",
        visible_to={"玩家", "gm"},
    )
    world.facts[fact.id] = fact

    player_view = world.view("玩家")
    guard_view = world.view("侍卫长")
    assert any(f["id"] == fact.id for f in player_view["facts"])
    assert all(f["id"] != fact.id for f in guard_view["facts"])


# ---------------- A3b / L3a：_world_context 信息迷雾修复 ----------------


def test_a3c_multi_viewer_fact_projection_and_sync(repo, world):
    """多个知情者不等于公开；新增知情者后原地更新同一条记忆。"""
    fact = Fact(
        subject="玩家",
        predicate="经历",
        object="曾在北境见过国王",
        visible_to={"玩家", "国王", "gm"},
    )
    world.facts[fact.id] = fact

    memory = LayeredMemory("p_multi_viewer", repo=repo)
    memory.sync_world_state(world, current_scene=1)
    item = memory.items[f"ws:fact:{fact.id}"]
    assert item.visible_to == ["国王", "玩家"]
    assert "经历" in memory.prompt_block(viewer="玩家")
    assert "经历" in memory.prompt_block(viewer="国王")
    assert "经历" not in memory.prompt_block(viewer="侍卫长")

    fact.visible_to.add("侍卫长")
    memory.sync_world_state(world, current_scene=2)
    item = memory.items[f"ws:fact:{fact.id}"]
    assert "侍卫长" in item.visible_to
    assert "经历" in memory.prompt_block(viewer="侍卫长")


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
        visible_to={"国王", "gm"},
    )
    world.facts[hidden.id] = hidden

    loop = NarrativeEngine(project=project)
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
        visible_to={"国王", "gm"},
    )
    world.facts[hidden.id] = hidden

    loop = NarrativeEngine(project=project)
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


def test_a8_override_audit(world):
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


# ---------------- A9：NPC 自主 ----------------


def test_a9_idle_three_turns_triggers_npc_event(project, world):
    world.characters["玩家"].location = "王宫"
    world.characters["国王"].location = "王宫"
    world.characters["侍卫长"].location = "王宫"

    engine = NarrativeEngine(project=project)
    result = asyncio.run(
        engine.play_turn(
            project=project,
            world_state=world,
            wait=True,
            idle_turns=3,
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
    memory.add_archive_item(
        "secret:玩家",
        "你的真实身份是王室的私生子。",
        tags=["secret", "asset"],
        visible_to=["玩家"],
        source="asset",
    )
    memory.add_archive_item(
        "secret:国王",
        "父亲失踪与你有关。",
        tags=["secret", "asset"],
        visible_to=["国王"],
        source="asset",
    )
    assert memory.retrieve("私生子", viewer="国王") == []
    assert [i.id for i in memory.retrieve("私生子", viewer="玩家")] == [
        "secret:玩家"
    ]
    assert [i.id for i in memory.retrieve("私生子", viewer="director")] == [
        "secret:玩家"
    ]
    assert "私生子" not in memory.prompt_block(viewer="国王")


def test_character_secret_stored_only_in_memory(repo):
    repo.upsert_character(
        "p_secret",
        "林夏",
        "primary",
        "冷静",
        "寻亲",
        secrets="她是前朝公主。",
    )
    characters = repo.list_characters("p_secret")
    assert "secrets" not in characters[0]

    items = repo.list_memory_items("p_secret")
    secret = next(
        item for item in items if item["id"].endswith("::secret:林夏")
    )
    assert secret["text"] == "她是前朝公主。"
    assert secret["visible_to"] == ["林夏"]

    repo.upsert_character(
        "p_secret", "林夏", "primary", "冷静", "寻亲", secrets=""
    )
    assert not any(
        item["id"].endswith("::secret:林夏")
        for item in repo.list_memory_items("p_secret")
    )


def test_foreshadow_truth_visible_to_director_and_known_character(repo):
    memory = LayeredMemory("p_fs", repo=repo)
    fs = Foreshadowing(
        description="旅店墙上的旧航海图",
        planted_in_scene="scene_1",
        target_revelation="航海图指向王室密道",
        visible_to=["林夏"],
    )
    memory.sync_foreshadowings([fs])

    truth_id = f"foreshadow_truth:{fs.foreshadow_id}"
    assert [i.id for i in memory.retrieve("王室密道", viewer="林夏")] == [
        truth_id
    ]
    assert memory.retrieve("王室密道", viewer="阿泽") == []
    assert [
        i.id for i in memory.retrieve("王室密道", viewer="director")
    ] == [truth_id]
    # 描述与真相共享 scope：不知情角色也检索不到线索
    assert memory.retrieve("航海图", viewer="阿泽") == []


def test_foreshadow_retroactive_conflict_blocks(project):
    engine = NarrativeEngine(project=project)
    project.scene_count = 3
    fs = Foreshadowing(
        description="宫廷密令",
        planted_in_scene="scene_1",
        target_revelation="国王早已知道真相",
        visible_to=["不存在的角色"],
    )

    issues = asyncio.run(engine.check_foreshadow_conflicts(project, fs))
    assert any(
        issue["severity"] == "major" and "不存在的角色" in issue["conflict"]
        for issue in issues
    )

    class _StubDirectorCrew:
        def director(self):
            return object()

    async def _fake_kickoff(agent, prompt, timeout_s=60.0):
        return (
            '{"passed": false, "conflicts": ['
            '{"severity": "major", "conflict": "与历史场景记忆冲突",'
            ' "evidence": "scene_1 中该角色尚未出场"}]}'
        )

    engine.crew = _StubDirectorCrew()
    engine._kickoff = _fake_kickoff
    fs.visible_to = []
    issues = asyncio.run(engine.check_foreshadow_conflicts(project, fs))
    assert any(
        issue["severity"] == "major"
        and "历史场景记忆" in issue["conflict"]
        for issue in issues
    )


# ---------------- 自由输入与渲染 ----------------


def test_freeform_text_enters_narrative_pipeline_without_action_parser(
    project, world
):
    action = "把账单折成纸船，放进街角的积水里"
    engine = NarrativeEngine(project=project)
    result = asyncio.run(
        engine.play_turn(
            project=project,
            world_state=world,
            action_text=action,
        )
    )

    assert result.status == "ok"
    assert result.state.time_minutes == world.time_minutes + 1
    assert result.state_delta.events[-1].summary == action


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


# ---------------- StoryEngine 配额与超时（已迁入 API 层） ----------------


def test_timeout_returns_immediately(tmp_path, project, world, monkeypatch):
    """StoryEngine.play_turn 用 asyncio.wait_for 包住回合。"""
    import asyncio
    from storyloom.api.engine import StoryEngine, engine as _global

    async def _slow(self, **kwargs):
        await asyncio.sleep(0.2)

    monkeypatch.setattr(NarrativeEngine, "play_turn", _slow)

    # 用临时 StoryEngine 实例，避免污染全局缓存
    from storyloom.api.engine import StoryEngine
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


def test_quota_rejects_when_no_turns_left(tmp_path, project, world):
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


# ---------------- 导演模式不回归 ----------------


def test_director_mode_turn_runs_without_touching_game_entry(project, world):
    engine = NarrativeEngine(project=project)
    result = asyncio.run(
        engine.play_turn(
            project=project,
            world_state=world,
            mode="director",
            goal="让雾更浓，压住码头的灯光。",
            action_text="让雾更浓",
        )
    )
    assert result.status == "ok"
    assert result.text
    assert result.state.mode == "director"
