"""惰性角色唤醒测试（无需 API Key）

覆盖：
- 不在场重要角色只有在 wake_character 被调用时才创建 Agent
- 已在场 / 背景 / 不存在的角色不会被唤醒
- 同一场景内重复唤醒命中缓存，不重复消耗 LLM 调用
- 每次场景的唤醒预算生效
- 唤醒记录会进入 actor_log 用的 transcript
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import yaml

from storyloom.crews.scene_crew.offscreen import parse_pending_request
from storyloom.crews.scene_crew.tools import (
    CharacterWakeRegistry,
    split_wake_output,
)
from storyloom.engine.narrative import NarrativeEngine
from storyloom.memory.models import CharacterAsset, NovelProject

_TASK_TEMPLATES = yaml.safe_load(
    (
        Path(__file__).resolve().parents[2]
        / "src"
        / "storyloom"
        / "crews"
        / "scene_crew"
        / "config"
        / "tasks.default.yaml"
    ).read_text(encoding="utf-8")
)


class StubMemory:
    def __init__(self):
        self.scenes = []
        self.archive = []
        self.condensed = []
        self.items = {}

    def prompt_block(self, viewer=None):
        return ""

    def retrieval_block(self, query, k=3, viewer=None):
        return ""

    def add_scene(self, **kwargs):
        self.scenes.append(kwargs)

    def add_condensed(self, **kwargs):
        self.condensed.append(kwargs)

    def add_archive_item(self, **kwargs):
        self.archive.append(kwargs)
        item = SimpleNamespace(
            id=kwargs["item_id"],
            text=kwargs["text"],
            source=kwargs.get("source", "asset"),
            scene_index=kwargs.get("scene_index", 0),
            created_at="",
        )
        self.items[item.id] = item

    def _drop(self, item_id):
        self.items.pop(item_id, None)


SIDE_STAGE_JSON = (
    '{"facts":"林晚在码头见过老周半夜搬走一只木箱。",'
    '"short_term":"林晚连夜蹲守码头，看见老周把木箱搬上无牌照货船。",'
    '"long_term":"林晚确认老周替人转移货物，码头线索坐实。",'
    '"key_event":"老周向走私船转移关键木箱，被林晚目击。",'
    '"worldbook":["林晚与老周互相知道对方在码头夜间活动。",'
    '"老周曾替不明雇主转移一只木箱。"],'
    '"perspectives":{'
    '"林晚":"我一直在码头蹲守，看见老周半夜搬走一只木箱。",'
    '"老周":"我搬木箱时被林晚远远看见了。"},'
    '"messages":[{"from":"老周","to":"玩家","content":"别去码头。"}]}'
)


class StubAgent:
    def __init__(self, name: str, reply: str):
        self.name = name
        self.reply = reply
        self.prompts = []

    def kickoff(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(raw=self.reply)


class StubCrew:
    def __init__(self, replies: dict, offscreen_reply: str = SIDE_STAGE_JSON):
        self.replies = replies
        self.agents = {}
        self.created = []
        self.offscreen_agent = StubAgent("offscreen", offscreen_reply)

    def build_protagonist(self, char, extra_tools=None):
        if char.name not in self.agents:
            self.agents[char.name] = StubAgent(
                char.name, self.replies.get(char.name, f"{char.name}的回应")
            )
            self.created.append(char.name)
        return self.agents[char.name]

    def build_offscreen_director(self):
        return self.offscreen_agent

    def task_prompt(self, key, **values):
        """复用真实 YAML 模板，验证占位符与生产代码一致。"""
        return _TASK_TEMPLATES[key]["description"].format(**values)


def make_project() -> NovelProject:
    return NovelProject(
        project_id="wake_test",
        title="唤醒测试",
        style="克制",
        characters=[
            CharacterAsset(
                name="玩家",
                importance_tier="primary",
                persona="刚回港的陌生人",
                motivation="查清真相",
            ),
            CharacterAsset(
                name="林晚",
                importance_tier="primary",
                persona="说话绕弯子，习惯先观察",
                motivation="掩盖自己当年的选择",
            ),
            CharacterAsset(
                name="老周",
                importance_tier="secondary",
                persona="码头老工人，消息灵通",
                motivation="保住饭碗",
            ),
            CharacterAsset(
                name="路人甲",
                importance_tier="background",
                persona="看热闹",
                motivation="无事发生",
            ),
        ],
        locations=[],
    )


def make_registry(
    *,
    max_wakes: int = 2,
    reply: str = "林晚在电话那头沉默了一会儿，说：别再查了。",
    reply_zhou: str = "老周含糊地应了一声，说：我什么都不知道。",
    memory=None,
    offscreen_reply: str = SIDE_STAGE_JSON,
    defer_side_stage: bool = False,
):
    crew = StubCrew(
        {"林晚": reply, "老周": reply_zhou},
        offscreen_reply=offscreen_reply,
    )
    registry = CharacterWakeRegistry(
        crew=crew,
        project=make_project(),
        present_chars=["玩家"],
        scene_brief="玩家在旅店打听父亲失踪的线索",
        memory=memory,
        scene_index=7,
        max_wakes=max_wakes,
        defer_side_stage=defer_side_stage,
    )
    return registry, crew


def test_offscene_character_is_lazy_until_woken():
    registry, crew = make_registry()
    assert crew.created == []

    result = registry.make_tool(source="director").run(
        character="林晚", reason="玩家提到了她的名字"
    )

    assert "林晚在电话那头" in result
    assert crew.created == ["林晚"]
    assert len(crew.agents["林晚"].prompts) == 1
    prompt = crew.agents["林晚"].prompts[0]
    assert "玩家在旅店打听父亲失踪的线索" in prompt
    assert "玩家提到了她的名字" in prompt
    assert "说话绕弯子" in prompt
    assert "【沉睡期间经历】" in prompt
    assert "【此刻回应】" in prompt

    assert registry.wake_count == 1
    assert len(registry.records) == 1
    assert "林晚" in registry.transcript_block()


def test_present_background_and_unknown_are_rejected():
    registry, crew = make_registry()

    present = registry.make_tool(source="director").run(character="玩家")
    background = registry.make_tool(source="director").run(character="路人甲")
    unknown = registry.make_tool(source="director").run(character="不存在的人")

    assert "已在场" in present
    assert "背景角色" in background
    assert "没有角色" in unknown
    assert crew.created == []
    assert registry.wake_count == 0


def test_repeat_wake_uses_cache_without_extra_llm_call():
    registry, crew = make_registry()
    tool = registry.make_tool(source="director")

    first = tool.run(character="林晚", reason="第一次")
    second = tool.run(character="林晚", reason="第二次")

    assert "林晚在电话那头" in first
    assert "林晚在电话那头" in second
    assert "缓存" in second
    assert len(crew.agents["林晚"].prompts) == 1
    assert registry.wake_count == 1


def test_wake_budget_limits_new_characters():
    registry, crew = make_registry(max_wakes=1)
    tool = registry.make_tool(source="director")

    tool.run(character="林晚")
    blocked = tool.run(character="老周")

    assert "预算已用完" in blocked
    assert crew.created == ["林晚"]
    assert "老周" not in crew.agents
    assert registry.wake_count == 1


def test_present_protagonist_tool_records_source():
    registry, _ = make_registry()

    registry.make_tool(source="protagonist:玩家").run(
        character="老周", reason="玩家想托他打听码头的人"
    )

    block = registry.transcript_block()
    assert "protagonist:玩家" in block
    assert "老周" in block


def test_woken_character_first_supplements_dormant_experience():
    reply = (
        "【沉睡期间经历】我一直在码头蹲守，看见老周半夜搬走一只木箱。\n"
        "【此刻回应】别信老周，他在替人办事。"
    )
    memory = StubMemory()
    registry, crew = make_registry(reply=reply, memory=memory)

    result = registry.make_tool(source="director").run(
        character="林晚", reason="玩家想确认码头目击者"
    )

    assert "【沉睡期间经历】" in result
    assert "码头蹲守" in result
    assert "别信老周" in result

    record = registry.records[0]
    assert record.experience == "我一直在码头蹲守，看见老周半夜搬走一只木箱。"
    assert record.response == "别信老周，他在替人办事。"
    assert record.side_stage is not None

    # 检测到老周后，侧台导演只调用一次
    assert len(crew.offscreen_agent.prompts) == 1

    # 共同事实 + 林晚视角 + 老周视角 + 发给玩家的消息
    assert len(memory.scenes) == 4
    facts, lin, zhou, message = memory.scenes

    assert facts["present_characters"] == ["林晚", "老周"]
    assert facts["scene_index"] == 7
    assert facts["key"].startswith("offscreen:ss_")
    # 短期记忆用导演压缩好的幕间近景，而不是照抄 facts
    assert "连夜蹲守" in facts["prose"]

    assert lin["present_characters"] == ["林晚"]
    assert "码头蹲守" in lin["prose"]

    assert zhou["present_characters"] == ["老周"]
    assert "被林晚远远看见" in zhou["prose"]

    assert message["present_characters"] == ["玩家"]
    assert "别去码头" in message["prose"]

    # 导演压缩好的材料分别直达长期记忆与关键事件
    assert len(memory.condensed) == 2
    long_item, key_item = memory.condensed
    assert long_item["tier"] == "long_term"
    assert "码头线索坐实" in long_item["text"]
    assert long_item["visible_to"] == ["林晚", "老周"]
    assert long_item["source"] == "side_stage"
    assert key_item["tier"] == "key_events"
    assert "走私船转移关键木箱" in key_item["text"]
    assert "key_event" in key_item["tags"]

    # 持久事实逐条写入世界书（archive），不另建事件表
    assert len(memory.archive) == 5
    (
        world_relation,
        world_box,
        world_lin,
        world_zhou,
        world_msg,
    ) = memory.archive

    assert world_relation["item_id"].endswith(":world:0")
    assert world_relation["visible_to"] == ["林晚", "老周"]
    assert world_relation["source"] == "side_stage"
    assert "worldbook" in world_relation["tags"]
    assert "互相知道对方在码头夜间活动" in world_relation["text"]

    assert world_box["item_id"].endswith(":world:1")
    assert "替不明雇主转移" in world_box["text"]

    assert world_lin["item_id"].endswith(":p:林晚")
    assert world_lin["visible_to"] == ["林晚"]
    assert "码头蹲守" in world_lin["text"]

    assert world_zhou["visible_to"] == ["老周"]
    assert "被林晚远远看见" in world_zhou["text"]

    assert world_msg["item_id"].startswith("offscreen_msg:")
    assert world_msg["visible_to"] == ["玩家"]
    assert "别去码头" in world_msg["text"]

    block = registry.transcript_block()
    assert "沉睡期间经历：我一直在码头蹲守" in block
    assert "此刻回应：别信老周" in block
    assert "侧台事实：林晚在码头见过老周" in block
    assert "侧台消息：老周 → 玩家：别去码头" in block


def test_explicit_involves_resolves_side_stage_before_wake():
    reply = (
        "【沉睡期间经历】我照旧在码头附近转。\n"
        "【此刻回应】我会盯着老周。"
    )
    registry, crew = make_registry(reply=reply)

    result = registry.make_tool(source="director").run(
        character="林晚",
        reason="玩家想确认码头目击者",
        involves="老周",
    )

    # 先裁决侧台，再把已确认经历注入角色提示词
    assert len(crew.offscreen_agent.prompts) == 1
    prompt = crew.agents["林晚"].prompts[0]
    assert "【侧台已确认的经历（必须以此为准，不得矛盾）】" in prompt
    assert "我一直在码头蹲守" in prompt

    # 角色自述与侧台冲突时，以侧台视角为准
    record = registry.records[0]
    assert record.experience == "我一直在码头蹲守，看见老周半夜搬走一只木箱。"
    assert "【侧台事实】" in result


def test_side_stage_event_is_reused_across_two_wakes():
    reply_lin = (
        "【沉睡期间经历】我在码头附近转。\n"
        "【此刻回应】我盯着老周。"
    )
    reply_zhou = (
        "【沉睡期间经历】我在搬货。\n"
        "【此刻回应】别多问。"
    )
    registry, crew = make_registry(
        reply=reply_lin, reply_zhou=reply_zhou
    )
    tool = registry.make_tool(source="director")

    tool.run(character="林晚", reason="确认目击者", involves="老周")
    tool.run(character="老周", reason="确认他当晚行踪", involves="林晚")

    # 同一组参与者复用同一张事件卡，不重复调用侧台导演
    assert len(crew.offscreen_agent.prompts) == 1
    assert registry.records[0].side_stage.event_id == (
        registry.records[1].side_stage.event_id
    )


def test_unstructured_wake_output_falls_back_to_reply():
    experience, reply = split_wake_output("只有一句回应")
    assert experience == ""
    assert reply == "只有一句回应"


def test_invalid_or_unavailable_participants_skip_side_stage():
    registry, crew = make_registry()

    registry.make_tool(source="director").run(
        character="林晚",
        reason="顺口一提",
        involves="玩家, 路人甲, 不存在的人",
    )

    assert crew.offscreen_agent.prompts == []
    assert registry.records[0].side_stage is None


def test_invalid_side_stage_json_falls_back_to_single_character_memory():
    reply = (
        "【沉睡期间经历】我在码头见过老周。\n"
        "【此刻回应】别去码头。"
    )
    memory = StubMemory()
    registry, crew = make_registry(
        reply=reply,
        memory=memory,
        offscreen_reply="这不是 JSON",
    )

    registry.make_tool(source="director").run(
        character="林晚", reason="确认目击者"
    )

    assert len(crew.offscreen_agent.prompts) == 1
    assert registry.records[0].side_stage is None
    # 侧台失败时退回单角色私有记忆
    assert len(memory.scenes) == 1
    assert memory.scenes[0]["present_characters"] == ["林晚"]
    assert memory.archive == []
    assert memory.condensed == []


def test_side_stage_without_compressed_fields_falls_back_to_facts():
    """旧模型只输出 facts 时，仍按确定性压缩写入长期记忆与世界书。"""
    memory = StubMemory()
    registry, crew = make_registry(
        memory=memory,
        offscreen_reply=(
            '{"facts":"林晚在码头见过老周半夜搬走一只木箱。"}'
        ),
    )

    registry.make_tool(source="director").run(
        character="林晚", reason="确认目击者", involves="老周"
    )

    event = registry.records[0].side_stage
    assert event is not None
    assert event.short_summary
    assert event.long_summary
    assert event.key_event == ""
    assert event.worldbook_entries == [event.facts]

    # 短期用兜底压缩文本，长期仍直达 long_term，不写关键事件
    assert "搬走一只木箱" in memory.scenes[0]["prose"]
    assert [item["tier"] for item in memory.condensed] == ["long_term"]
    assert "搬走一只木箱" in memory.condensed[0]["text"]
    assert memory.archive[0]["item_id"].endswith(":facts")
    assert "搬走一只木箱" in memory.archive[0]["text"]


# ---------------------------------------------------------------------------
# 异步侧台：游戏模式只登记 pending 记忆条目，回合间再推进
# ---------------------------------------------------------------------------


def test_game_mode_wake_registers_pending_instead_of_calling_llm():
    memory = StubMemory()
    registry, crew = make_registry(
        memory=memory, defer_side_stage=True
    )

    result = registry.make_tool(source="director").run(
        character="林晚",
        reason="玩家想确认码头目击者",
        involves="老周",
    )

    assert "已登记异步唤醒" in result
    assert "后续回合" in result
    assert "不要让在场角色替对方回答" in result

    # 没有现场 LLM 调用，也没有立即写短期记忆
    assert crew.created == []
    assert crew.offscreen_agent.prompts == []
    assert memory.scenes == []
    assert registry.wake_count == 1

    # 请求本身写成 side_stage_pending 记忆条目
    assert len(memory.archive) == 1
    pending = memory.archive[0]
    assert pending["source"] == "side_stage_pending"
    assert pending["visible_to"] == []
    assert "side_stage_pending" in pending["tags"]

    payload = parse_pending_request(pending["text"])
    assert payload["focus"] == "林晚"
    assert payload["participants"] == ["林晚", "老周"]
    assert payload["reason"] == "玩家想确认码头目击者"
    assert payload["scene_index"] == 7

    # 同一角色重复登记不会产生第二条 pending
    again = registry.make_tool(source="director").run(
        character="林晚", reason="再次尝试"
    )
    assert "无需重复登记" in again
    assert len(memory.archive) == 1


def test_drain_side_stage_lands_memory_worldbook_and_echo():
    reply = (
        "【沉睡期间经历】我一直在码头蹲守。\n"
        "【此刻回应】别信老周，他在替人办事。"
    )
    memory = StubMemory()
    registry, crew = make_registry(
        memory=memory, reply=reply, defer_side_stage=True
    )
    registry.make_tool(source="director").run(
        character="林晚",
        reason="玩家想确认码头目击者",
        involves="老周",
    )
    assert crew.created == []
    project = registry.project

    engine = NarrativeEngine(crew=crew, memory=memory)
    echo = asyncio.run(
        engine.drain_side_stage(
            project=project,
            present_chars=["玩家"],
            scene_brief="玩家在旅店等回信",
        )
    )

    # 回合间才真正唤醒角色并裁决侧台
    assert crew.created == ["林晚"]
    assert len(crew.offscreen_agent.prompts) == 1
    assert "侧台回响" in echo
    assert "林晚" in echo
    assert "别信老周" in echo
    assert "侧台事实" in echo
    assert "侧台消息：老周 → 玩家" in echo

    # 事件内容按层进入短期记忆、长期记忆、关键事件与世界书
    assert len(memory.scenes) == 4
    # 2 条世界书持久事实 + 2 条私有视角 + 1 条消息 + 已登记的 pending
    assert len(memory.archive) == 6
    assert sum(
        1 for item in memory.archive if item["source"] == "side_stage"
    ) == 5
    assert memory.archive[-1]["visible_to"] == ["玩家"]
    assert [item["tier"] for item in memory.condensed] == [
        "long_term",
        "key_events",
    ]
    assert "码头线索坐实" in memory.condensed[0]["text"]
    assert "走私船转移关键木箱" in memory.condensed[1]["text"]

    # pending 条目在推进后被清理，不进入世界书检索
    assert all(
        item.source != "side_stage_pending"
        for item in memory.items.values()
    )


def test_drain_side_stage_skips_character_who_is_now_present():
    memory = StubMemory()
    registry, crew = make_registry(
        memory=memory, defer_side_stage=True
    )
    registry.make_tool(source="director").run(character="林晚")
    project = registry.project

    engine = NarrativeEngine(crew=crew, memory=memory)
    echo = asyncio.run(
        engine.drain_side_stage(
            project=project,
            present_chars=["玩家", "林晚"],
            scene_brief="林晚已经到场",
        )
    )

    assert echo == ""
    assert crew.created == []
    assert memory.scenes == []
    assert all(
        item.source != "side_stage_pending"
        for item in memory.items.values()
    )
