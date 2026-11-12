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
from storyloom.engine.narrative import NarrativeEngine, TurnBoot
from storyloom.memory import (
    DemotionRule,
    LayeredMemory,
    MemoryItem,
    MemorySettings,
    TierSpec,
)
from storyloom.memory.scoring import score_compressed_importance
from storyloom.memory.models import CharacterAsset, LocationAsset, NovelProject
from storyloom.memory.state import WorldState


class FakeCompressor:
    """伪装压缩模型：记录 prompt，返回可预测的压缩结果。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
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


def test_history_overflow_merges_inside_history_not_world_book(repo):
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
        key_events_compress_into="key_events",
        key_events_compress_max_chars=240,
    )
    memory = LayeredMemory(
        "p_key_events_overflow", repo=repo, settings=settings, compress_fn=fake
    )

    for index in range(4):
        memory._put(
            MemoryItem(
                id=f"key_events:{index}",
                tier="key_events",
                text=f"事件：旧事件 {index}；影响：世界继续运转。",
                summary=f"事件 {index}",
                importance=1.0,
                pinned=True,
                scene_index=index,
            )
        )

    memory.consolidate()

    assert memory.counts()["key_events"] <= 3
    assert memory.counts()["archive"] == 0
    assert all(
        item.source != "compressed"
        for item in memory._items_in("archive")
    )


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
