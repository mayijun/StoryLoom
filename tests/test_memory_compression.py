"""分层记忆压缩回归测试（全部使用 mock，不访问真实 LLM）。

覆盖本轮实际试玩暴露的问题：
- 短期 / 长期只是拼接，没有真正压缩；
- 正史与长期记忆同样冗长，与世界书职责重叠；
- 工作记忆作为一个层级意义不大；
- 冷却记忆难以进入世界书；
- 失败回合仍写入记忆。
"""

import asyncio

import pytest

from storyloom.db import CrewConfigRepository, reset_engines, reset_repositories
from storyloom.engine.narrative import NarrativeEngine, TurnBoot, _apply_memory_facts
from storyloom.memory import (
    DemotionRule,
    LayeredMemory,
    MemoryItem,
    MemorySettings,
    TierSpec,
    VectorBackend,
)
from storyloom.memory.scoring import score_compressed_importance
from storyloom.memory.models import CharacterAsset, LocationAsset, NovelProject
from storyloom.memory.state import WorldState


class FakeCompressor:
    """伪装压缩模型：记录 prompt，返回可预测的压缩结果。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.scopes: list[list[str]] = []

    def __call__(self, prompt: str, scope: list[str]) -> str:
        self.prompts.append(prompt)
        self.scopes.append(list(scope))
        history_calls = sum("「关键事件」" in item for item in self.prompts)
        long_calls = sum("「长期剧情记忆」" in item for item in self.prompts)
        if "「关键事件」" in prompt:
            return f"事件：第{history_calls}次关键转折；影响：主线推进"
        return (
            f"主线：第{long_calls}段压缩事实；"
            "伏笔：旧钥匙的来历仍未解开"
        )


@pytest.fixture
def repo(tmp_path):
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'memory_compress.db'}"
    yield CrewConfigRepository(url)
    reset_repositories()
    reset_engines()


def _scene_prose(index: int) -> str:
    return (
        "海雾从码头压下来，风把旗子吹得猎猎作响，空气里全是咸味。"
        "林凡把缺角的航海图交给老周，老周说这是你父亲留下的线索。"
        f"这是第{index}次确认。"
    ) * 2


def test_short_to_long_uses_llm_compression_prompt(repo):
    fake = FakeCompressor()
    memory = LayeredMemory("p_compress_long", repo=repo, compress_fn=fake)

    for index in range(7):
        memory.add_scene(index, _scene_prose(index), brief=f"行动 {index}")

    assert len(fake.prompts) == 1
    prompt = fake.prompts[0]
    assert "「长期剧情记忆」" in prompt
    assert "伏笔" in prompt and "主线" in prompt
    assert "删除" in prompt and "环境" in prompt

    long_items = memory._items_in("long_term")
    assert len(long_items) == 1
    assert long_items[0].text.startswith("主线：")
    assert len(long_items[0].text) <= 220
    assert long_items[0].importance >= 0.35


def test_long_to_history_keeps_only_key_events(repo):
    fake = FakeCompressor()
    memory = LayeredMemory("p_compress_key_events", repo=repo, compress_fn=fake)

    for index in range(9):
        memory._put(
            MemoryItem(
                id=f"long:{index}",
                tier="long_term",
                text=f"场景 {index}：林凡继续赶路，路边风景很好。",
                summary=f"场景 {index} 摘要",
                importance=0.5,
                scene_index=index,
                last_hit_scene=index,
            )
        )

    memory.consolidate()

    key_events = memory._items_in("key_events")
    assert len(key_events) == 1
    # 正史不再默认 pinned，创作者可通过阈值让它冷却到世界书
    assert key_events[0].pinned is False
    assert key_events[0].text.startswith("事件：")
    assert len(key_events[0].text) <= 160

    prompt = next(item for item in fake.prompts if "「关键事件」" in item)
    assert "只记录" in prompt
    assert "改变主线走向" in prompt or "改变世界格局" in prompt
    assert "忽略日常互动" in prompt


def test_fallback_compression_drops_scenery_keeps_key_fact(repo):
    # 不传 compress_fn：走确定性兜底，也必须选择性保留关键事实
    memory = LayeredMemory("p_compress_fallback", repo=repo)

    for index in range(7):
        memory.add_scene(index, _scene_prose(index), brief=f"行动 {index}")

    long_text = "\n".join(
        item.text for item in memory._items_in("long_term")
    )
    assert "航海图" in long_text
    assert "线索" in long_text
    # 环境描写不应成段进入长期记忆
    assert "猎猎作响" not in long_text
    assert all(len(item.text) <= 220 for item in memory._items_in("long_term"))


@pytest.mark.parametrize("compress_into", ["key_events", "archive"])
def test_key_events_overflow_cools_coldest_without_losing_information(
    repo, compress_into
):
    fake = FakeCompressor()
    settings = MemorySettings(
        tiers=[
            TierSpec(
                name="short_term",
                max_items=6,
                compress_batch=3,
                compress_into="long_term",
                compress_max_chars=220,
            ),
            TierSpec(
                name="long_term",
                max_items=8,
                compress_batch=4,
                compress_into="key_events",
                compress_max_chars=160,
            ),
        ],
        key_events_max_items=3,
        key_events_compress_into=compress_into,
        key_events_compress_max_chars=240,
        reheat_hits=2,
    )
    memory = LayeredMemory(
        f"p_key_events_overflow_{compress_into}",
        repo=repo,
        settings=settings,
        compress_fn=fake,
    )
    memory._put(
        MemoryItem(
            id="long:recent",
            tier="long_term",
            text="林凡正在青云宗守护封印。",
            summary="林凡守护青云宗封印",
            scene_index=10,
            last_hit_scene=10,
        )
    )
    events = [
        MemoryItem(
            id="key_events:hot",
            tier="key_events",
            text="林凡在青云宗击败来敌，改变主线。",
            summary="林凡在青云宗击败来敌",
            importance=0.95,
            scene_index=0,
            last_hit_scene=0,
            visible_to=["林凡"],
        ),
        MemoryItem(
            id="key_events:cold",
            tier="key_events",
            text="北境旧王病逝，诸国格局改变。",
            summary="北境旧王病逝",
            importance=0.9,
            scene_index=1,
            last_hit_scene=1,
        ),
        MemoryItem(
            id="key_events:warm",
            tier="key_events",
            text="南海舰队叛变，改变海上格局。",
            summary="南海舰队叛变",
            importance=0.85,
            scene_index=2,
            hits=1,
            last_hit_scene=2,
        ),
        MemoryItem(
            id="key_events:new",
            tier="key_events",
            text="西漠神女公开真实身份。",
            summary="西漠神女公开身份",
            importance=0.8,
            scene_index=3,
            last_hit_scene=3,
        ),
    ]
    original_ids = {item.id for item in events}
    for item in events:
        memory._put(item)
    original_cold = memory.items["key_events:cold"].model_copy(deep=True)

    memory.consolidate()

    assert memory.counts()["key_events"] == 3
    assert memory.counts()["archive"] == 1
    assert set(memory.items) == original_ids | {"long:recent"}
    assert memory.items["key_events:hot"].tier == "key_events"
    cold = memory.items["key_events:cold"]
    assert cold.tier == "archive"
    assert cold.source == "demoted"
    assert {"demoted", "key_event_overflow"}.issubset(cold.tags)
    for field in (
        "id", "text", "summary", "importance", "scene_index",
        "hits", "adoptions", "last_hit_scene", "visible_to",
    ):
        assert getattr(cold, field) == getattr(original_cold, field)
    assert fake.prompts == []

    reloaded = LayeredMemory(
        memory.project_id, repo=repo, settings=settings, compress_fn=fake
    )
    assert reloaded.items[cold.id].tier == "archive"
    assert reloaded.items[cold.id].text == original_cold.text

    memory.retrieve("北境旧王", current_scene=11)
    assert cold.tier == "archive"
    memory.retrieve("北境旧王", current_scene=12)
    assert cold.tier == "key_events"
    assert cold.source == "reheated"
    assert cold.text == original_cold.text

    # 回温后由下一次整理按最新热度选冷事件，不回退到压缩或丢弃。
    memory.consolidate()
    assert memory.counts()["key_events"] == 3
    assert memory.counts()["archive"] == 1
    assert set(memory.items) == original_ids | {"long:recent"}
    assert cold.tier == "key_events"
    assert fake.prompts == []


def test_key_event_overflow_uses_embedding_relevance(repo):
    def embedding(text: str) -> list[float]:
        if "dragon" in text.lower() or "龙" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]

    memory = LayeredMemory(
        "p_key_events_embedding",
        repo=repo,
        settings=MemorySettings(tiers=[], key_events_max_items=1),
        vector=VectorBackend(embedding_fn=embedding),
    )
    memory._put(
        MemoryItem(
            id="long:recent",
            tier="long_term",
            text="dragon attacks the city",
            summary="dragon attacks",
        )
    )
    memory._put(
        MemoryItem(
            id="key_events:semantic_hot",
            tier="key_events",
            text="巨龙摧毁王城。",
            summary="巨龙摧毁王城",
            scene_index=0,
        )
    )
    memory._put(
        MemoryItem(
            id="key_events:cold",
            tier="key_events",
            text="北境旧王病逝。",
            summary="北境旧王病逝",
            scene_index=1,
        )
    )

    memory.consolidate()

    assert memory.items["key_events:semantic_hot"].tier == "key_events"
    assert memory.items["key_events:cold"].tier == "archive"


def test_protected_key_events_may_exceed_capacity_without_data_loss(repo):
    fake = FakeCompressor()
    memory = LayeredMemory(
        "p_key_events_protected",
        repo=repo,
        settings=MemorySettings(tiers=[], key_events_max_items=1),
        compress_fn=fake,
    )
    memory._put(
        MemoryItem(id="key:pinned", tier="key_events", pinned=True)
    )
    memory._put(
        MemoryItem(
            id="key:foreshadow", tier="key_events", active_foreshadow=True
        )
    )

    memory.consolidate()

    assert memory.counts()["key_events"] == 2
    assert memory.counts()["archive"] == 0
    assert fake.prompts == []


def test_minor_long_term_memory_demotes_to_world_book_and_reheats(repo):
    memory = LayeredMemory("p_demote_flow", repo=repo)
    memory._put(
        MemoryItem(
            id="lt_minor",
            tier="long_term",
            text="旅店老板又擦了一遍杯子，没有说什么。",
            summary="旅店老板擦杯子",
            importance=score_compressed_importance(
                "旅店老板又擦了一遍杯子，没有说什么。"
            ),
            scene_index=1,
            last_hit_scene=1,
        )
    )
    assert memory.items["lt_minor"].importance < 0.35

    demoted = memory.evaluate_demotion(12)
    assert [item.id for item in demoted] == ["lt_minor"]
    assert memory.items["lt_minor"].tier == "archive"
    assert memory.items["lt_minor"].source == "demoted"
    assert "demoted" in memory.items["lt_minor"].tags

    memory.retrieve("旅店老板", current_scene=13)
    memory.retrieve("旅店老板", current_scene=14)
    assert memory.items["lt_minor"].tier == "long_term"
    assert memory.items["lt_minor"].source == "reheated"


def test_simulated_31_turn_playthrough_tier_flow(repo):
    """复刻本轮试玩：31 个回合后核心层应稳定为 短期4 / 长期5 / 历史1。"""
    fake = FakeCompressor()
    memory = LayeredMemory("p_play_31", repo=repo, compress_fn=fake)

    for turn in range(1, 32):
        memory.add_scene(
            scene_index=turn,
            prose=(
                f"第{turn}回合，林凡在青云宗追查失踪案。"
                "他把新发现的线索交给掌门，掌门答应三日后给答复。"
            ),
            brief=f"行动 {turn}",
        )

    counts = memory.counts()
    assert "working" not in counts
    assert counts["short_term"] == 4
    assert counts["long_term"] == 5
    assert counts["key_events"] == 1
    assert counts["archive"] == 0

    key_events = memory._items_in("key_events")
    assert key_events[0].pinned is False
    assert key_events[0].text.startswith("事件：")
    assert len(key_events[0].text) <= 240

    block = memory.prompt_block()
    assert "【关键事件】" in block
    assert key_events[0].text in block

    texts = [
        item.text
        for item in memory.items.values()
        if item.tier in ("short_term", "long_term", "key_events")
    ]
    assert len(texts) == len(set(texts))


def test_prompt_block_separates_history_and_world_book(repo):
    memory = LayeredMemory("p_prompt_split", repo=repo)
    memory.add_archive_item(
        "asset:location:禁地",
        "青云宗后山禁地，外人不得入内。",
        tags=["location"],
    )
    memory._put(
        MemoryItem(
            id="key_events:1",
            tier="key_events",
            text="事件：林凡拜入青云宗；影响：主线开启。",
            summary="林凡拜入青云宗",
            importance=1.0,
            pinned=True,
            scene_index=3,
        )
    )

    block = memory.prompt_block()
    assert "【关键事件】" in block
    assert "事件：林凡拜入青云宗" in block
    assert "青云宗后山禁地" not in block

    retrieval = memory.retrieval_block("后山禁地")
    assert "青云宗后山禁地" in retrieval
    assert set(memory.counts()) == {
        "short_term", "long_term", "key_events", "archive"
    }


def test_turn_working_context_uses_player_action_text():
    project = NovelProject(
        project_id="p_working",
        title="青云宗",
        style="film_narrative",
        characters=[
            CharacterAsset(
                name="玩家",
                importance_tier="primary",
                persona="外门弟子",
                motivation="查清失踪案",
            )
        ],
        locations=[LocationAsset(name="青云宗", description="山门")],
    )
    memory = LayeredMemory("p_working")
    state = WorldState.from_project(project)

    engine = NarrativeEngine(project=project, memory=memory)
    result = asyncio.run(
        engine.play_turn(
            project=project,
            world_state=state,
            action_text="观察四周",
            max_retries=0,
        )
    )
    assert result.status == "ok"
    assert memory.working.intent == "观察四周"
    assert memory.working.scene_brief == "观察四周"
    assert "【本轮意图】观察四周" in memory.prompt_block()


def test_creator_can_configure_each_layer_threshold(tmp_path):
    """创作者可在 YAML 中分别设定每层容量、压缩批量与降级阈值。"""
    config = tmp_path / "memory_config.yaml"
    config.write_text(
        """
tiers:
  - name: short_term
    max_items: 2
    compress_batch: 1
    compress_into: long_term
  - name: long_term
    max_items: 3
    compress_batch: 2
    compress_into: key_events
key_events:
  max_items: 9
demotion:
  long_term:
    importance_threshold: 0.88
    miss_scenes: 2
  key_events:
    importance_threshold: 0.77
    miss_scenes: 5
  reheat_hits: 1
""",
        encoding="utf-8",
    )

    settings = MemorySettings.load(str(config))

    assert (settings.tiers[0].max_items, settings.tiers[0].compress_batch) == (2, 1)
    assert (settings.tiers[1].max_items, settings.tiers[1].compress_batch) == (3, 2)
    assert settings.key_events_max_items == 9
    assert settings.rule_for("long_term").importance_threshold == 0.88
    assert settings.rule_for("long_term").miss_scenes == 2
    assert settings.rule_for("key_events").importance_threshold == 0.77
    assert settings.rule_for("key_events").miss_scenes == 5
    assert settings.reheat_hits == 1


def test_demotion_rules_fall_back_to_global_thresholds():
    """旧配置只有全局阈值时，两层都回落到全局值。"""
    settings = MemorySettings(
        demotion_threshold=0.6, demotion_miss_scenes=3
    )
    for tier in ("long_term", "key_events"):
        rule = settings.rule_for(tier)
        assert rule.importance_threshold == 0.6
        assert rule.miss_scenes == 3


def test_compression_never_merges_different_visible_to(repo):
    """不同可见范围不得合并；无同组同伴时最旧单条无损降级。"""
    settings = MemorySettings(
        tiers=[
            TierSpec(
                name="short_term", max_items=1,
                compress_batch=2, compress_into="long_term",
            ),
        ],
        key_events_max_items=20,
    )
    memory = LayeredMemory(
        "p_scope_compress", repo=repo, settings=settings,
        compress_fn=FakeCompressor(),
    )
    memory.add_scene(
        1, "张三知道的第一条线索。", present_characters=["张三"]
    )
    memory.add_scene(
        2, "李四知道的第二条线索。", present_characters=["李四"]
    )

    assert [
        item for item in memory._items_in("long_term")
        if item.source == "compressed"
    ] == []
    demoted = memory.items["scene:1"]
    assert demoted.tier == "archive"
    assert demoted.source == "demoted"
    assert demoted.visible_to == ["张三"]
    assert {"demoted", "no_peer"}.issubset(demoted.tags)
    assert "第一条线索" in demoted.text


def test_easiest_threshold_demotes_long_and_key_events_to_world_book(repo):
    """用最容易触发的阈值：每层只留 1 条、每次压 1 条、阈值 0.99、miss=2。"""
    settings = MemorySettings(
        tiers=[
            TierSpec(
                name="short_term",
                max_items=1,
                compress_batch=1,
                compress_into="long_term",
                compress_max_chars=220,
            ),
            TierSpec(
                name="long_term",
                max_items=1,
                compress_batch=1,
                compress_into="key_events",
                compress_max_chars=160,
            ),
        ],
        key_events_max_items=20,
        demotion_rules={
            "long_term": DemotionRule(
                importance_threshold=0.99, miss_scenes=2
            ),
            "key_events": DemotionRule(
                importance_threshold=0.99, miss_scenes=2
            ),
        },
    )
    memory = LayeredMemory(
        "p_easiest_demote", repo=repo, settings=settings,
        compress_fn=FakeCompressor(),
    )

    for turn in range(1, 7):
        memory.add_scene(turn, _scene_prose(turn), brief=f"行动 {turn}")
    # 再推进一个场景，让最后一条长期记忆也满足冷却条件
    memory.evaluate_demotion(7)

    counts = memory.counts()
    assert counts["long_term"] == 0
    assert counts["key_events"] == 0
    assert counts["archive"] > 0

    archived = memory._items_in("archive")
    assert all(item.source == "demoted" for item in archived)
    remained_tiers = {
        tag for item in archived for tag in item.tags
    }
    assert {"long_term", "key_events"} <= remained_tiers


def test_demotion_skips_pinned_and_active_foreshadowing(repo):
    settings = MemorySettings(
        demotion_rules={
            "long_term": DemotionRule(
                importance_threshold=0.99, miss_scenes=0
            ),
            "key_events": DemotionRule(
                importance_threshold=0.99, miss_scenes=0
            ),
        }
    )
    memory = LayeredMemory("p_guard", repo=repo, settings=settings)
    memory._put(
        MemoryItem(
            id="pinned_key_events",
            tier="key_events",
            text="事件：世界终局。",
            importance=0.1,
            pinned=True,
            scene_index=1,
            last_hit_scene=1,
        )
    )
    memory._put(
        MemoryItem(
            id="foreshadow_long",
            tier="long_term",
            text="伏笔：旧钥匙仍未被使用。",
            importance=0.1,
            active_foreshadow=True,
            scene_index=1,
            last_hit_scene=1,
        )
    )

    assert memory.evaluate_demotion(100) == []
    assert memory.items["pinned_key_events"].tier == "key_events"
    assert memory.items["foreshadow_long"].tier == "long_term"


class DualCompressor:
    """文言存储 + 白话展示的伪装压缩模型。"""

    def __init__(self, with_display: bool = True) -> None:
        self.prompts: list[str] = []
        self.with_display = with_display

    def __call__(self, prompt: str, scope: list[str]) -> str:
        self.prompts.append(prompt)
        if not self.with_display:
            return "【文言存储】\n林凡入青云，败敌，主线易。"
        return (
            "【文言存储】\n林凡入青云，败敌，主线易。\n"
            "【白话展示】\n林凡进入青云宗，击败敌人，主线发生变化。"
        )


def _classical_settings() -> MemorySettings:
    return MemorySettings(
        tiers=[
            TierSpec(
                name="short_term",
                max_items=2,
                compress_batch=2,
                compress_into="long_term",
                compress_max_chars=200,
            )
        ],
        compression_style="classical",
    )


def _seed_short_term(memory: LayeredMemory) -> None:
    for index in range(3):
        memory._put(
            MemoryItem(
                id=f"short:{index}",
                tier="short_term",
                text="林凡进入青云宗，击败敌人，主线发生变化。",
                summary="林凡进入青云宗，击败敌人，主线发生变化。",
                scene_index=index,
            )
        )


def test_classical_compression_keeps_vernacular_for_display(repo):
    fake = DualCompressor()
    settings = _classical_settings()
    assert MemorySettings.from_dict(settings.to_dict()).classical_compression
    memory = LayeredMemory(
        "p_classical_dual", repo=repo, settings=settings, compress_fn=fake
    )
    _seed_short_term(memory)

    memory.consolidate()

    assert "文言存储" in fake.prompts[0]
    item = memory._items_in("long_term")[0]
    assert item.text == "林凡入青云，败敌，主线易。"
    assert item.summary == "林凡进入青云宗，击败敌人，主线发生变化。"
    assert "classical_storage" in item.tags

    block = memory.prompt_block(viewer="director")
    assert item.summary in block
    assert item.text not in block
    item.tier = "archive"
    memory._put(item)
    rag = memory.retrieval_block(
        "林凡进入青云宗，击败敌人", viewer="director"
    )
    assert item.summary in rag
    assert item.text not in rag

    reloaded = LayeredMemory(
        memory.project_id, repo=repo, settings=settings, compress_fn=fake
    )
    stored = reloaded.items[item.id]
    assert stored.text == item.text
    assert stored.summary == item.summary


def test_classical_compression_without_display_falls_back_to_vernacular(repo):
    fake = DualCompressor(with_display=False)
    memory = LayeredMemory(
        "p_classical_fallback",
        repo=repo,
        settings=_classical_settings(),
        compress_fn=fake,
    )
    _seed_short_term(memory)

    memory.consolidate()

    item = memory._items_in("long_term")[0]
    assert item.text == item.summary
    assert "classical_storage" not in item.tags
    assert "林凡入青云" not in item.text
    assert "林凡进入青云宗" in item.text
    assert "林凡入青云" not in memory.prompt_block(viewer="director")


def test_agent_memory_fact_uses_display_text_in_classical_mode(repo):
    memory = LayeredMemory(
        "p_classical_agent",
        repo=repo,
        settings=MemorySettings(tiers=[], compression_style="classical"),
    )
    _apply_memory_facts(
        memory=memory,
        facts=[
            {
                "tier": "short_term",
                "text": "林凡入青云，败敌。",
                "display_text": "林凡进入青云宗，击败敌人。",
            }
        ],
        scene_index=1,
        prose="林凡进入青云宗，击败敌人。",
        brief="",
        present_chars=["林凡"],
    )

    item = memory._items_in("short_term")[0]
    assert item.text == "林凡入青云，败敌。"
    assert item.summary == "林凡进入青云宗，击败敌人。"
    assert "classical_storage" in item.tags
    assert "林凡入青云" not in memory.prompt_block(viewer="director")


def test_agent_memory_fact_without_display_falls_back_to_prose(repo):
    memory = LayeredMemory(
        "p_classical_agent_fallback",
        repo=repo,
        settings=MemorySettings(tiers=[], compression_style="classical"),
    )
    _apply_memory_facts(
        memory=memory,
        facts=[{"tier": "short_term", "text": "林凡入青云，败敌。"}],
        scene_index=1,
        prose="林凡进入青云宗，击败敌人，主线因此改变。",
        brief="",
        present_chars=["林凡"],
    )

    items = memory._items_in("short_term")
    assert items
    assert all("林凡入青云" not in item.summary for item in items)
    assert "林凡入青云" not in memory.prompt_block(viewer="director")


def test_compression_preserves_same_scope(repo):
    """同 visible_to 的条目可以压缩，产物保持完全相同的范围。"""
    settings = MemorySettings(
        tiers=[
            TierSpec(
                name="short_term", max_items=1,
                compress_batch=2, compress_into="long_term",
            ),
        ],
        key_events_max_items=20,
    )
    memory = LayeredMemory(
        "p_same_scope", repo=repo, settings=settings,
        compress_fn=FakeCompressor(),
    )
    memory.add_scene(1, "张三看到黑衣人。", present_characters=["张三"])
    memory.add_scene(2, "张三追进小巷。", present_characters=["张三"])

    long_term = memory._items_in("long_term")
    assert len(long_term) == 1
    assert long_term[0].visible_to == ["张三"]
    assert "scene:1" not in memory.items
    assert "scene:2" not in memory.items


def test_empty_compress_output_falls_back_without_losing_sources(repo):
    """压缩方返回空串时走确定性兜底，来源仍被合并而不是丢失。"""
    settings = MemorySettings(
        tiers=[
            TierSpec(
                name="short_term", max_items=1,
                compress_batch=2, compress_into="long_term",
            ),
        ],
        key_events_max_items=20,
    )
    memory = LayeredMemory(
        "p_empty_compress", repo=repo, settings=settings,
        compress_fn=lambda prompt, scope: "",
    )
    memory.add_scene(1, "第一条线索。", present_characters=["张三"])
    memory.add_scene(2, "第二条线索。", present_characters=["张三"])

    long_term = memory._items_in("long_term")
    assert len(long_term) == 1
    assert long_term[0].text
    assert long_term[0].visible_to == ["张三"]
    assert "scene:1" not in memory.items
    assert "scene:2" not in memory.items


def test_all_pinned_overflow_does_not_loop(repo):
    """全部受保护时允许暂时超容量，且 consolidate 必须能退出。"""
    settings = MemorySettings(
        tiers=[
            TierSpec(
                name="short_term", max_items=0,
                compress_batch=2, compress_into="long_term",
            ),
        ],
        key_events_max_items=20,
    )
    memory = LayeredMemory(
        "p_all_pinned", repo=repo, settings=settings,
        compress_fn=FakeCompressor(),
    )
    for index in (1, 2):
        memory._put(
            MemoryItem(
                id=f"pinned:{index}",
                project_id="p_all_pinned",
                tier="short_term",
                text=f"受保护记忆 {index}",
                pinned=True,
                scene_index=index,
                visible_to=["张三" if index == 1 else "李四"],
            )
        )

    assert memory.consolidate() == []
    assert len(memory._items_in("short_term")) == 2
    assert all(item.pinned for item in memory._items_in("short_term"))
