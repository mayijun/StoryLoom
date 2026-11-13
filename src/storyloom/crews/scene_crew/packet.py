"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

统一 Agent 输出契约。

所有 Agent 只输出一个 JSON 对象，不同字段由不同消费方读取：

    prose            正文段      → 渲染
    choices          选项段      → 玩家下一步
    stage            舞台段      → StageDirective
    decision/state   裁决段      → 世界状态
    npc_actions      NPC 段      → 行动提案
    issues           质检段      → 一致性 / 质量标记

这样每个 Agent 只需要一次调用，调用方按段取用，避免为每种用途
维护一套独立的输出格式和解析逻辑。
"""

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from storyloom.memory.base import MEMORY_ITEM_MAX_CHARS
from storyloom.memory.state import (
    ActionProposal,
    AdjudicationResult,
    StageDirective,
    StageScene,
    StateDelta,
    WorldEvent,
    WorldState,
)


class AgentChoice(BaseModel):
    """可提交给玩家的一条自然语言选项。"""

    text: str = ""
    hint: str = ""


class AgentOperation(BaseModel):
    """Agent 提出的一条行动（NPC 或导演）。"""

    actor: str = ""
    kind: str = "other"
    target: str = ""
    detail: str = ""


_TIER_CHOICES = frozenset({"short_term"})


class MemoryFact(BaseModel):
    """Agent 在同一次 JSON 输出里附带的预压缩记忆事实。

    调用次数不增加——Agent 在输出 prose/narrative/state 的同时，
    直接给出需要进入 short_term 层的核心事实（场景摘要）。
    更上层的 long_term / key_events / archive 由 memory 系统后台
    的 consolidate() + compress.py 负责，Agent 不越过这道边界。

    每条 text 必须已经是压缩好的版本，长度不超过 MEMORY_ITEM_MAX_CHARS。
    """

    tier: str = "short_term"
    text: str = ""
    # text 的白话展示版；文言记忆存储模式下必填，否则可省略
    display_text: str = ""
    known_by: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    def is_valid(self) -> bool:
        return (
            self.tier in _TIER_CHOICES
            and bool(self.text.strip())
            and len(self.text) <= MEMORY_ITEM_MAX_CHARS
        )


class AgentPacket(BaseModel):
    """所有 Agent 共用的 JSON 信封；未使用的段保持默认值。"""

    # 正文段
    prose: str = ""
    # 选项段
    choices: List[AgentChoice] = Field(default_factory=list)
    # 舞台段
    stage: List[Dict[str, Any]] = Field(default_factory=list)
    # 裁决段
    decision: str = "allow"          # allow | reject | direct
    narrative: str = ""
    reason: str = ""
    state: Dict[str, Any] = Field(default_factory=dict)
    available: List[str] = Field(default_factory=list)
    # NPC 段
    npc_actions: List[AgentOperation] = Field(default_factory=list)
    # 质检段
    issues: List[str] = Field(default_factory=list)
    # 记忆事实段：Agent 在同一次输出里附带的预压缩核心记忆（可选）
    # 每条必须已经是压缩好的版本，长度 ≤ MEMORY_ITEM_MAX_CHARS
    memory_facts: List[MemoryFact] = Field(default_factory=list)


PACKET_CONTRACT = f"""\
只输出一个 JSON 对象，不要 Markdown 代码围栏或额外说明。可用字段：
{{
  "prose": "正文",
  "choices": [{{"text": "玩家可尝试的自然语言行动", "hint": "风险或代价提示"}}],
  "stage": [{{"kind": "bg", "params": {{"location": "地点"}}}}],
  "decision": "allow | reject | direct",
  "narrative": "本轮裁决事实",
  "reason": "裁决理由",
  "state": {{"time_delta": 1, "characters": {{}}, "flags": {{}}, "relationships": {{}}}},
  "available": ["可去地点"],
  "npc_actions": [{{"actor": "角色", "kind": "talk|move|observe|other", "target": "", "detail": "自然语言行动"}}],
  "issues": ["一致性问题"],
  "memory_facts": [
    {{
      "tier": "short_term",
      "text": "本回合场景摘要，≤ {MEMORY_ITEM_MAX_CHARS} 字。已经是压缩好的最终形态。",
      "display_text": "text 的白话展示版；启用文言记忆存储时必填，否则可省略。",
      "known_by": ["知晓该事实的角色名，可省略"],
      "tags": ["scene | foreshadow | ...，可省略"]
    }}
  ]
}}
只填写当前任务需要的字段，其余可省略。

# ─────────────────────────────────────────────────────
# memory_facts：Agent 只负责 short_term 一层
# ─────────────────────────────────────────────────────
#
# 你的 JSON 里 **必须** 附带 memory_facts，把本回合场景压缩成
# 1-3 条写入。memory_facts 是你这次 kickoff 输出的一部分，
# 调用次数 **不会** 增加。
#
# 重要职责边界：
#
#   你（Agent）→ 只写 short_term（场景摘要）
#                  保留人物选择、承诺/契约、关键物品/伏笔线索，
#                  删除环境描写、情绪渲染、重复对话。
#
#   memory 系统后台 → 把 short_term 进一步压缩成
#                     long_term（主线进展）、
#                     key_events（关键转折）、
#                     archive（世界真相/资产）。
#
#   你 **不要** 尝试写 long_term / key_events / archive，
#   这些层级由记忆系统自己的 compress.py 处理。
#
# 硬约束：每条 text ≤ {MEMORY_ITEM_MAX_CHARS} 字。
# 若任务提示启用文言记忆存储：text 用文言文，display_text 用同义白话文；
# 未启用时可省略 display_text。
#
# ─── 实战示例 ───
#
# 假设你写了下面这段 prose（384 字）：
#
#   "大厅里点着油蜡火把，昏黄的光在石板地面上投下摇曳的影子。
#   林慢慢走过一排排祖先画像，脚步声在空旷的大厅里回响。
#   老管家王福迎了上来，皱纹里藏着忧虑。「少爷，您终于回来了。
#   老爷当年留下的遗物……我们找到了航海图的残片。」
#   林心头一震，握紧了口袋里的那枚铜钥匙——那是母亲临终前给他的。
#   王福压低声音：「地下室入口在壁炉后面，但被老主人加了三道锁。」
#   他递给林一张泛黄的纸，上面画着X标记，旁边写着一串数字。
#   林把纸折好塞进怀里，决定今晚就潜入地下室，
#   去揭开父亲十年前那场失踪案的真相。
#   窗外雷声滚过，城堡陷入一片昏暗。"
#
# 你应该输出下面的 memory_facts：
#
#   "memory_facts": [
#     {{
#       "tier": "short_term",
#       "text": "林回到祖宅城堡，老管家王福交出父亲遗留的航海图残片与地下室入口提示（壁炉后，三道锁）。林决心夜里潜入地下室揭开父亲当年失踪真相。",
#       "tags": ["scene", "foreshadow"]
#     }}
#   ]
#
# ─── 自检清单 ───
#
#   □ 每条 text 都比 prose 短得多（压缩率 ≥ 70%）
#   □ 每条 text ≤ {MEMORY_ITEM_MAX_CHARS} 字（硬上限）
#   □ 没有环境描写、没有情绪渲染、没有"仿佛""似乎"
#   □ 关键事实不丢：人物、地点、行动、结果、承诺、关键物品
#   □ tier 只写 short_term（long_term/key_events/archive 是 memory 系统后台负责的）
#   □ known_by 只在信息有保密范围时填（"只有林和王福知道"）
#   □ tags 让记忆系统在压缩/降级时保留正确分类

# ─────────────────────────────────────────────────────
# 可用字段定义（JSON 结构）
# ─────────────────────────────────────────────────────
{{
  "prose": "正文",
  "choices": [{{"text": "玩家可尝试的自然语言行动", "hint": "风险或代价提示"}}],
  "stage": [{{"kind": "bg", "params": {{"location": "地点"}}}}],
  "decision": "allow | reject | direct",
  "narrative": "本轮裁决事实",
  "reason": "裁决理由",
  "state": {{"time_delta": 1, "characters": {{}}, "flags": {{}}, "relationships": {{}}}},
  "available": ["可去地点"],
  "npc_actions": [{{"actor": "角色", "kind": "talk|move|observe|other", "target": "", "detail": "自然语言行动"}}],
  "issues": ["一致性问题"],
  "memory_facts": [
    {{
      "tier": "short_term",
      "text": "本回合场景摘要，≤ {MEMORY_ITEM_MAX_CHARS} 字。已经是压缩好的版本。",
      "known_by": ["知晓该事实的角色名，可省略"],
      "tags": ["scene | foreshadow | ...，可省略"]
    }}
  ]
}}
只填写当前任务需要的字段，其余可省略。

关于 memory_facts：每次输出 **必须** 附带 memory_facts，把这回合场景压缩成
1-3 条 short_term 写入。调用次数 **不会** 增加——memory_facts 就是你这次
JSON 输出的一部分。long_term / key_events / archive 由 memory 系统后台负责，
你不要越权写这些层级。"""


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_agent_packet(raw: str) -> AgentPacket:
    """从模型输出中解析统一 JSON；纯文本输出退化为正文。"""
    text = (raw or "").strip()
    if not text:
        return AgentPacket()

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return AgentPacket(prose=text)
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return AgentPacket(prose=text)
    if not isinstance(data, dict):
        return AgentPacket(prose=text)

    choices: List[AgentChoice] = []
    seen = set()
    raw_choices = data.get("choices")
    if raw_choices is None:
        raw_choices = data.get("suggested_actions")
    for item in _as_list(raw_choices):
        if isinstance(item, str):
            item_text, hint = item.strip(), ""
        elif isinstance(item, dict):
            item_text = str(
                item.get("text") or item.get("label") or ""
            ).strip()
            hint = str(item.get("hint") or "").strip()
        else:
            continue
        if not item_text or item_text in seen:
            continue
        seen.add(item_text)
        choices.append(AgentChoice(text=item_text, hint=hint))
        if len(choices) >= 4:
            break

    operations: List[AgentOperation] = []
    for item in _as_list(data.get("npc_actions")):
        if not isinstance(item, dict):
            continue
        actor = str(item.get("actor") or "").strip()
        if not actor:
            continue
        operations.append(
            AgentOperation(
                actor=actor,
                kind=str(item.get("kind") or "other"),
                target=str(item.get("target") or ""),
                detail=str(item.get("detail") or item.get("text") or ""),
            )
        )

    issues = [
        str(item).strip()
        for item in _as_list(data.get("issues"))
        if str(item).strip()
    ]
    stage = [
        item for item in _as_list(data.get("stage"))
        if isinstance(item, dict) and item.get("kind")
    ]
    decision = str(data.get("decision") or "allow").strip().lower()
    if decision not in ("allow", "reject", "direct"):
        decision = "allow"

    memory_facts: List[MemoryFact] = []
    for item in _as_list(data.get("memory_facts")):
        if not isinstance(item, dict):
            continue
        fact = MemoryFact(
            tier=str(item.get("tier") or "short_term"),
            text=str(item.get("text") or "").strip(),
            display_text=str(item.get("display_text") or "").strip(),
            known_by=[
                str(v).strip()
                for v in _as_list(item.get("known_by"))
                if str(v).strip()
            ],
            tags=[
                str(v).strip()
                for v in _as_list(item.get("tags"))
                if str(v).strip()
            ],
        )
        if fact.is_valid():
            memory_facts.append(fact)
        else:
            # 无效 fact 只打警告，不阻断；调用方 narrative 会做最后兜底
            pass

    return AgentPacket(
        prose=str(data.get("prose") or "").strip(),
        choices=choices,
        stage=stage,
        decision=decision,
        narrative=str(data.get("narrative") or "").strip(),
        reason=str(data.get("reason") or "").strip(),
        state=_as_dict(data.get("state")),
        available=[
            str(item) for item in _as_list(data.get("available"))
            if str(item).strip()
        ],
        npc_actions=operations,
        issues=issues,
        memory_facts=memory_facts,
    )


def packet_to_delta(packet: AgentPacket) -> StateDelta:
    """把裁决段转成 StateDelta；字段缺失或非法时返回空增量。"""
    if not packet.state:
        return StateDelta()
    data = dict(packet.state)
    events = []
    for item in _as_list(data.get("events")):
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        events.append(
            WorldEvent(
                kind=str(item.get("kind") or "action"),
                actor=str(item.get("actor") or ""),
                summary=summary,
                data=_as_dict(item.get("data")),
            )
        )
    data["events"] = events
    try:
        return StateDelta.model_validate(data)
    except Exception:  # noqa: BLE001 - LLM 输出不可控，非法增量直接丢弃
        return StateDelta()


def packet_to_proposals(packet: AgentPacket) -> List[ActionProposal]:
    return [
        ActionProposal(
            actor=item.actor,
            kind=item.kind if item.kind in {
                "move", "attack", "talk", "use", "wait", "observe", "other"
            } else "other",
            target=item.target or None,
            detail=item.detail,
            source="npc",
        )
        for item in packet.npc_actions
    ]


def packet_to_result(
    packet: AgentPacket, default_narrative: str = ""
) -> AdjudicationResult:
    """把裁决段转成 AdjudicationResult。"""
    success = packet.decision != "reject"
    narrative = packet.narrative or packet.reason or default_narrative
    if not narrative and success:
        narrative = "世界接受了这个行动。"
    return AdjudicationResult(
        success=success,
        outcome=(
            "directed" if packet.decision == "direct"
            else "narrated" if success else "rejected"
        ),
        narrative=narrative,
        state_delta=packet_to_delta(packet),
        error_code=None if success else "rejected_by_referee",
        available=packet.available,
        quality_flag=None if success else "rejected",
        rule="llm_referee",
    )


def compose_scene(
    state_before: WorldState,
    state_after: WorldState,
    adjudication: AdjudicationResult,
    actor: str = "玩家",
    packet: Optional[AgentPacket] = None,
) -> StageScene:
    """把裁决结果与 Agent 正文/选项/舞台段装配成 StageScene。"""
    packet = packet or AgentPacket()
    directives: List[StageDirective] = []
    location = _actor_location(state_after)

    before_char = state_before.characters.get(actor)
    if before_char and before_char.location != location:
        directives.append(
            StageDirective(
                kind="move",
                params={
                    "from": before_char.location,
                    "to": location,
                    "time": state_after.format_time(),
                },
            )
        )

    directives.append(
        StageDirective(
            kind="bg",
            params={
                "location": location,
                "time": state_after.format_time(),
                "phase": state_after.arc.phase,
            },
        )
    )

    text = (packet.prose or adjudication.narrative or "").strip()
    if text:
        directives.append(StageDirective(kind="say", params={"text": text}))

    if not adjudication.success:
        directives.append(
            StageDirective(
                kind="effect",
                params={
                    "name": "blocked",
                    "error_code": (
                        adjudication.error_code or adjudication.outcome
                    ),
                    "available": adjudication.available,
                },
            )
        )

    # Agent 自带的舞台段（bgm / se / shake 等）直接追加
    for item in packet.stage:
        kind = str(item.get("kind") or "")
        if not kind:
            continue
        try:
            directives.append(
                StageDirective(
                    kind=kind, params=_as_dict(item.get("params"))
                )
            )
        except Exception:  # noqa: BLE001 - 非法指令跳过，不阻断回合
            continue

    choices: List[Dict[str, Any]] = []
    for item in packet.choices[:4]:
        choices.append(
            {
                "index": len(choices),
                "label": item.text,
                "text": item.text,
                "hint": item.hint,
                "source": "agent",
            }
        )

    # Agent 没有给建议时，保留确定性选项作为兜底。
    if not choices:
        choices = [
            {
                "index": index,
                "label": item["label"],
                "action": item["kind"],
                "target": item["target"],
                "hint": item.get("hint", ""),
                "source": "rules",
            }
            for index, item in enumerate(
                state_after.allowed_actions(actor)[:4]
            )
        ]

    if choices:
        directives.append(
            StageDirective(kind="choice", params={"options": choices})
        )

    directives.append(
        StageDirective(
            kind="show",
            params={
                "panel": "status",
                "time": state_after.format_time(),
                "turn": state_after.turn,
                "location": location,
                "characters": state_after.characters_at(location),
                "quality_flag": adjudication.quality_flag,
            },
        )
    )
    directives.append(StageDirective(kind="end", params={}))

    return StageScene(directives=directives, text=text, choices=choices)


def _actor_location(state: WorldState) -> str:
    player = state.characters.get("玩家")
    if player:
        return player.location
    if state.characters:
        return next(iter(state.characters.values())).location
    return ""


__all__ = [
    "AgentChoice",
    "AgentOperation",
    "AgentPacket",
    "PACKET_CONTRACT",
    "compose_scene",
    "packet_to_delta",
    "packet_to_proposals",
    "packet_to_result",
    "parse_agent_packet",
]
