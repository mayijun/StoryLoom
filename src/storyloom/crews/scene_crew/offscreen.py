"""同步侧台事件：裁决沉睡角色之间的互动，并补全参与者记忆。

设计原则：
- 一次互动只由一个 OffscreenDirector 统一裁决，不做两两对话；
- 输出「共同事实 + 各自视角 + 延迟消息」，并直接产出压缩好的
  short_term / long_term / key_event / worldbook 材料；
- 事实写入所有参与者可见的记忆，视角只写入本人，消息只写入收件人；
- 不单独建事件表：压缩材料分别直达短期记忆、长期记忆、关键事件
  与世界书（archive 检索层），靠现有记忆层完成后续冷却与召回；
- 游戏模式使用异步侧台：唤醒只登记为 pending 记忆条目，在回合间
  推进后以「侧台回响」进入下一回合；
- 侧台解析失败时不阻断唤醒，退回单角色补述。
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from storyloom.memory.base import MEMORY_ITEM_MAX_CHARS
from storyloom.memory.models import CharacterAsset, NovelProject
from storyloom.memory.scoring import summarize

_NAME_SPLIT_RE = re.compile(r"[,，、;；\s]+")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

#: 异步侧台待推进请求：以 archive 记忆条目存放，不占用世界书检索。
PENDING_SOURCE = "side_stage_pending"
PENDING_TAG = "side_stage_pending"


@dataclass
class SideStageEvent:
    """一次侧台互动的权威事件卡。

    侧台导演除了给出共同事实与各自视角，还会直接产出已经压缩好的
    分层材料，由 ``write_side_stage_memory`` 分别写入短期记忆、
    长期记忆、关键事件与世界书，避免系统事后再压缩一遍。
    """

    event_id: str
    facts: str
    perspectives: Dict[str, str]
    participants: List[CharacterAsset] = field(default_factory=list)
    messages: List[Dict[str, str]] = field(default_factory=list)
    #: 短期记忆用的幕间近景记录（保留关键细节）
    short_summary: str = ""
    #: 长期记忆用的压缩梗概（只留因果与结果）
    long_summary: str = ""
    #: 构成不可逆转折时写入关键事件；空字符串表示不写入
    key_event: str = ""
    #: 应进入世界书的持久事实，每条一句
    world_facts: List[str] = field(default_factory=list)

    @property
    def participant_names(self) -> List[str]:
        return [char.name for char in self.participants]

    def perspective_for(self, name: str) -> str:
        return (self.perspectives.get(name) or "").strip()

    @property
    def worldbook_entries(self) -> List[str]:
        """世界书条目：优先用导演给出的持久事实，缺省回落到共同事实。"""
        entries = [text.strip() for text in self.world_facts if text.strip()]
        return entries or [self.facts.strip()]



def normalize_names(raw: Any) -> List[str]:
    """接受 str / list，拆成去重的角色名列表。"""
    if isinstance(raw, str):
        parts = _NAME_SPLIT_RE.split(raw)
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(item) for item in raw]
    else:
        parts = []
    result: List[str] = []
    for part in parts:
        name = part.strip()
        if name and name not in result:
            result.append(name)
    return result


def select_participants(
    project: NovelProject,
    present_chars: List[str],
    focus: str,
    raw_names: Any,
    limit: int = 2,
) -> List[CharacterAsset]:
    """从显式传入的名字里筛选可参与侧台的角色。"""
    present = set(present_chars)
    selected: List[CharacterAsset] = []
    for name in normalize_names(raw_names):
        if len(selected) >= limit:
            break
        char = project.get_character(name)
        if char is None:
            continue
        if char.name == focus or char.name in present:
            continue
        if char.importance_tier == "background":
            continue
        selected.append(char)
    return selected


def detect_participants(
    project: NovelProject,
    present_chars: List[str],
    focus: str,
    text: str,
    limit: int = 2,
) -> List[CharacterAsset]:
    """从角色自述里检测提到的其他沉睡角色。"""
    present = set(present_chars)
    hits: List[CharacterAsset] = []
    for char in project.characters:
        if char.name == focus or char.name in present:
            continue
        if char.importance_tier == "background":
            continue
        # 单字名容易误伤，只对显式传入的名字生效
        if len(char.name) < 2:
            continue
        if char.name in text:
            hits.append(char)
    hits.sort(key=lambda char: text.find(char.name))
    return hits[:limit]


def resolve_side_stage(
    *,
    crew: Any,
    project: NovelProject,
    participants: List[CharacterAsset],
    scene_brief: str,
    reason: str,
    focus: str,
    intent: str = "",
    draft_experience: str = "",
) -> Optional[SideStageEvent]:
    """调用侧台导演裁决一次互动；失败返回 None，由调用方降级。"""
    if len(participants) < 2:
        return None
    prompt = build_side_stage_prompt(
        participants=participants,
        scene_brief=scene_brief,
        reason=reason,
        intent=intent,
        draft_experience=draft_experience,
    )
    try:
        agent = crew.build_offscreen_director()
        output = agent.kickoff(prompt)
        raw = str(getattr(output, "raw", output) or "")
    except Exception:  # noqa: BLE001 - 侧台失败不阻断主流程
        return None

    data = _parse_json_object(raw)
    if not data:
        return None

    facts = str(data.get("facts") or "").strip()
    if not facts:
        return None

    # 导演直接产出已压缩的分层材料；缺省时做确定性压缩兜底
    short_summary = (
        str(data.get("short_term") or "").strip()
        or summarize(facts, limit=MEMORY_ITEM_MAX_CHARS)
    )
    long_summary = (
        str(data.get("long_term") or "").strip()
        or summarize(facts, limit=MEMORY_ITEM_MAX_CHARS)
    )
    key_event = str(data.get("key_event") or "").strip()

    world_raw = data.get("worldbook")
    if isinstance(world_raw, str):
        world_raw = [world_raw]
    world_facts: List[str] = []
    for entry in world_raw or []:
        if not isinstance(entry, str):
            continue
        text = entry.strip()
        if text and text not in world_facts:
            world_facts.append(text)
        if len(world_facts) >= 4:
            break

    perspectives_raw = data.get("perspectives") or {}
    perspectives: Dict[str, str] = {}
    if isinstance(perspectives_raw, dict):
        for char in participants:
            value = perspectives_raw.get(char.name)
            if isinstance(value, str) and value.strip():
                perspectives[char.name] = value.strip()
    for char in participants:
        if char.name not in perspectives:
            perspectives[char.name] = (
                draft_experience
                if char.name == focus and draft_experience
                else facts
            )

    messages: List[Dict[str, str]] = []
    for item in data.get("messages") or []:
        if len(messages) >= 2:
            break
        if not isinstance(item, dict):
            continue
        sender = str(item.get("from") or focus).strip()
        recipient = str(item.get("to") or "").strip()
        content = str(item.get("content") or "").strip()
        if not recipient or not content:
            continue
        if project.get_character(recipient) is None:
            continue
        messages.append(
            {"from": sender, "to": recipient, "content": content}
        )

    return SideStageEvent(
        event_id=f"ss_{uuid.uuid4().hex[:8]}",
        facts=facts,
        perspectives=perspectives,
        participants=list(participants),
        messages=messages,
        short_summary=short_summary,
        long_summary=long_summary,
        key_event=key_event,
        world_facts=world_facts,
    )


def queue_side_stage(
    *,
    memory: Any,
    focus: CharacterAsset,
    participants: List[CharacterAsset],
    reason: str,
    scene_brief: str,
    intent: str,
    scene_index: int,
    source: str,
) -> Optional[str]:
    """登记一次异步唤醒/侧台互动。

    不建事件表：请求本身写成一条 ``source=side_stage_pending`` 的
    archive 记忆条目，回合间由 ``drain_side_stage`` 取出推进。
    返回待处理条目 id；memory 不支持 archive 时返回 None。
    """
    writer = getattr(memory, "add_archive_item", None) if memory else None
    if writer is None:
        return None
    pending_id = f"asp_{uuid.uuid4().hex[:8]}"
    payload = {
        "focus": focus.name,
        "participants": [char.name for char in participants],
        "reason": reason,
        "scene_brief": scene_brief,
        "intent": intent,
        "scene_index": scene_index,
        "source": source,
    }
    try:
        writer(
            item_id=f"side_stage_pending:{pending_id}",
            text=json.dumps(payload, ensure_ascii=False),
            scene_index=scene_index,
            importance=0.05,
            tags=[PENDING_TAG, "offscreen", "side_stage"],
            visibility="restricted",
            known_by=[],
            source=PENDING_SOURCE,
        )
    except Exception:  # noqa: BLE001 - 登记失败时由调用方退回同步
        return None
    return pending_id


def pending_side_stage(memory: Any) -> List[Any]:
    """按登记顺序返回尚未推进的异步侧台记忆条目。"""
    items = getattr(memory, "items", None) if memory else None
    if not isinstance(items, dict):
        return []
    pending = [
        item for item in items.values()
        if getattr(item, "source", "") == PENDING_SOURCE
    ]
    pending.sort(
        key=lambda item: (
            getattr(item, "scene_index", 0),
            getattr(item, "created_at", ""),
        )
    )
    return pending


def parse_pending_request(text: str) -> Optional[Dict[str, Any]]:
    """解析待推进条目里的 JSON；损坏条目返回 None。"""
    data = _parse_json_object(text)
    if not data or not data.get("focus"):
        return None
    return data


def drop_pending_side_stage(memory: Any, item_id: str) -> None:
    """推进完成后删除待处理条目。"""
    dropper = getattr(memory, "_drop", None)
    if dropper is None:
        return
    try:
        dropper(item_id)
    except Exception:  # noqa: BLE001 - 删除失败不影响本回合叙事
        pass


def write_side_stage_memory(
    *,
    memory: Any,
    project: NovelProject,
    event: SideStageEvent,
    scene_index: int,
) -> None:
    """把事件卡直接并入分层记忆，不单独建事件表。

    侧台导演已经产出压缩好的材料，这里按目标层分别落位：
    - ``short_term``：幕间近景记录，立即参与近期叙事；
    - ``long_term``：压缩梗概，直达长期记忆；
    - ``key_events``：只有不可逆转折才写入；
    - ``worldbook``（archive）：持久事实，供后续按相关性检索；
    - 各自视角与消息只给对应角色，保留误解、隐瞒与知情范围。
    """
    if memory is None:
        return
    names = event.participant_names
    short_text = event.short_summary or event.facts
    long_text = event.long_summary or event.facts
    try:
        # 短期记忆：所有参与者都知道的幕间近景
        memory.add_scene(
            scene_index=scene_index,
            prose=f"侧台事件：{short_text}",
            brief="侧台事件（不在场角色互动）",
            present_characters=names,
            key=f"offscreen:{event.event_id}:facts",
        )
        # 长期记忆：直接用导演压缩好的梗概，不再等阈值压缩
        _add_condensed(
            memory,
            tier="long_term",
            text=f"幕间经过：{long_text}",
            scene_index=scene_index,
            tags=["offscreen", "side_stage", "long_term"],
            known_by=names,
        )
        # 关键事件：只在导演判定为不可逆转折时写入
        if event.key_event:
            _add_condensed(
                memory,
                tier="key_events",
                text=event.key_event,
                scene_index=scene_index,
                tags=[
                    "offscreen",
                    "side_stage",
                    "key_event",
                ],
                known_by=names,
            )
        # 世界书：持久事实逐条落库，供流程与关系检索
        for index, entry in enumerate(event.worldbook_entries):
            item_id = (
                f"offscreen:{event.event_id}:facts"
                if len(event.worldbook_entries) == 1
                else f"offscreen:{event.event_id}:world:{index}"
            )
            _add_worldbook_item(
                memory,
                item_id=item_id,
                text=f"侧台事实：{entry}",
                scene_index=scene_index,
                tags=["offscreen", "side_stage", "worldbook"],
                known_by=names,
            )
        # 各自视角：只写本人，保留误解与隐瞒
        for name, text in event.perspectives.items():
            memory.add_scene(
                scene_index=scene_index,
                prose=f"{name}（侧台视角）：{text}",
                brief=f"{name}沉睡期间的经历",
                present_characters=[name],
                key=f"offscreen:{event.event_id}:{name}",
            )
            _add_worldbook_item(
                memory,
                item_id=f"offscreen:{event.event_id}:p:{name}",
                text=f"{name}（沉睡期间的私下经历）：{text}",
                scene_index=scene_index,
                tags=[
                    "offscreen",
                    "side_stage",
                    "worldbook",
                    "perspective",
                ],
                known_by=[name],
            )
        # 延迟消息：先补进收件人记忆，正文需要时再送达
        for message in event.messages:
            recipient = message["to"]
            if recipient in names:
                continue
            memory.add_scene(
                scene_index=scene_index,
                prose=(
                    f"你收到来自{message['from']}的消息："
                    f"{message['content']}"
                ),
                brief="侧台传来的消息",
                present_characters=[recipient],
                key=f"offscreen_msg:{event.event_id}:{recipient}",
            )
            _add_worldbook_item(
                memory,
                item_id=f"offscreen_msg:{event.event_id}:{recipient}",
                text=(
                    f"{message['from']}在沉睡期间给{recipient}传过消息："
                    f"{message['content']}"
                ),
                scene_index=scene_index,
                tags=["offscreen", "side_stage", "worldbook", "message"],
                known_by=[recipient],
            )
    except Exception:  # noqa: BLE001 - 记忆写入失败不阻断唤醒
        pass


def _add_condensed(
    memory: Any,
    *,
    tier: str,
    text: str,
    scene_index: int,
    tags: List[str],
    known_by: List[str],
) -> None:
    """写入导演已压缩好的长期记忆 / 关键事件。"""
    writer = getattr(memory, "add_condensed", None)
    if writer is None:
        return
    writer(
        tier=tier,
        text=text,
        scene_index=scene_index,
        tags=tags,
        known_by=known_by,
        source="side_stage",
    )


def _add_worldbook_item(
    memory: Any,
    *,
    item_id: str,
    text: str,
    scene_index: int,
    tags: List[str],
    known_by: List[str],
) -> None:
    """写入世界书（archive 检索层）。

    记忆实现没有 archive 能力时静默跳过，保持与旧测试桩兼容；
    ``source`` 固定为 ``side_stage``，避免被资产回填误清理。
    """
    writer = getattr(memory, "add_archive_item", None)
    if writer is None:
        return
    writer(
        item_id=item_id,
        text=text,
        scene_index=scene_index,
        tags=tags,
        known_by=known_by,
        source="side_stage",
    )


def build_side_stage_prompt(
    *,
    participants: List[CharacterAsset],
    scene_brief: str,
    reason: str,
    intent: str = "",
    draft_experience: str = "",
) -> str:
    profiles = "\n".join(
        f"- {char.name}（{char.importance_tier}）"
        f"性格/说话习惯：{char.persona}；当前动机：{char.motivation}"
        for char in participants
    )
    intent_block = f"【导演意图】{intent}\n" if intent else ""
    draft_block = (
        f"【被唤醒角色的草稿经历（可能有误，仅作参考）】\n{draft_experience}\n"
        if draft_experience
        else ""
    )
    return (
        "你是不出现在正文里的侧台导演，只裁决不在场角色之间已经/正在"
        "发生的互动。\n"
        f"【当前主场景】{scene_brief or '（未提供）'}\n"
        f"【唤醒原因】{reason or '需要补全沉睡期间的经历'}\n"
        f"{intent_block}"
        f"【参与者】\n{profiles}\n"
        f"{draft_block}"
        "输出一个 JSON 对象，不要输出任何其他文字，格式：\n"
        "{\n"
        '  "facts": "所有参与者都能观察到的客观事实，1~3 句",\n'
        '  "short_term": "幕间近景记录，保留关键细节，1~2 句",\n'
        '  "long_term": "压缩后的长期梗概，只留因果与结果，1 句",\n'
        '  "key_event": "若构成不可逆转折，写一条关键事件；否则空字符串",\n'
        '  "worldbook": ["值得长期检索的持久事实，每条一句；没有则空数组"],\n'
        '  "perspectives": {"角色名": "该角色自己的视角、误解或隐瞒，1~2 句"},\n'
        '  "messages": [{"from": "角色名", "to": "收件人名", '
        '"content": "消息内容"}]\n'
        "}\n"
        "规则：\n"
        "- facts 只写共同可观察的事实；秘密、误解、隐瞒只能放进对应视角；\n"
        "- short_term / long_term / worldbook 必须是你自己压缩好的文本，"
        "不要照抄 facts；\n"
        "- worldbook 只写关系变化、身份、位置、契约、承诺、秘密等可长期"
        "检索的持久事实，不写一次性动作细节；\n"
        "- key_event 只在发生不可逆转折时填写，日常走动留空；\n"
        "- perspectives 必须覆盖每个参与者；\n"
        "- 不要替在场角色行动，不要让他们凭空获得秘密；\n"
        "- messages 最多 2 条，收件人必须是作品中的角色；没有消息返回空数组；\n"
        "- 只输出 JSON，不要解释。"
    )


def _parse_json_object(text: str) -> Optional[dict]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    fenced = _JSON_FENCE_RE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


__all__ = [
    "PENDING_SOURCE",
    "PENDING_TAG",
    "SideStageEvent",
    "detect_participants",
    "drop_pending_side_stage",
    "normalize_names",
    "parse_pending_request",
    "pending_side_stage",
    "queue_side_stage",
    "resolve_side_stage",
    "select_participants",
    "write_side_stage_memory",
]
