"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

世界状态：双模式共用的客观真相容器。

设计纪律：
- Runtime 无状态：WorldState 不落 DB，每回合由请求传入、返回 state_delta；
- 只有 GameMaster 可以写 Fact；角色只能看到 view(agent_id)；
- 所有结构可 JSON 序列化。
"""

import uuid
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, Field

from storyloom.models import NovelProject


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class Fact(BaseModel):
    """客观事实：GM 是唯一维护者"""

    id: str = Field(default_factory=lambda: new_id("fact"))
    subject: str
    predicate: str
    object: str
    truth: Literal["true", "false", "unknown"] = "true"
    known_by: Set[str] = Field(default_factory=set)
    asserted_by: Optional[str] = None
    source_event: str = ""


class CharState(BaseModel):
    """角色运行时状态（位置是人物在场性的唯一事实来源）"""

    name: str
    location: str = ""
    emotion: str = "平静"
    health: int = 100
    status: Literal["active", "absent", "dead", "imprisoned"] = "active"
    inventory: List[str] = Field(default_factory=list)
    goals: List[str] = Field(default_factory=list)
    # 角色相信的事实 id（M0 只做 known_by 过滤，belief 全量留到 M2）
    beliefs: List[str] = Field(default_factory=list)


class LocationState(BaseModel):
    """地点状态：出口与旅行耗时（分钟）"""

    name: str
    description: str = ""
    exits: Dict[str, int] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class ArcState(BaseModel):
    """叙事节拍：起承转合 + 张力目标 + 信息预算"""

    phase: Literal["setup", "rising", "climax", "resolution"] = "setup"
    tension_target: float = 0.3
    beats_remaining: int = 4
    info_budget: float = 1.0


class WorldEvent(BaseModel):
    """已发生事件（只追加，不回改）"""

    event_id: str = Field(default_factory=lambda: new_id("evt"))
    turn: int = 0
    world_time: int = 0
    kind: str = "action"
    actor: str = ""
    summary: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)


class Promise(BaseModel):
    """承诺 / 命运约束：带期限的叙事债务"""

    promise_id: str = Field(default_factory=lambda: new_id("prm"))
    description: str
    deadline_minutes: Optional[int] = None
    fulfilled: bool = False
    linked_fact: Optional[str] = None
    needs_review: bool = False


class StateDelta(BaseModel):
    """一次裁决产生的状态增量，由 GM 产出、commit 阶段合并"""

    time_delta: int = 0
    characters: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    locations: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    facts_set: List[Fact] = Field(default_factory=list)
    facts_remove: List[str] = Field(default_factory=list)
    flags: Dict[str, Any] = Field(default_factory=dict)
    relationships: Dict[str, int] = Field(default_factory=dict)
    arc: Dict[str, Any] = Field(default_factory=dict)
    events: List[WorldEvent] = Field(default_factory=list)
    promises_set: List[Promise] = Field(default_factory=list)
    promises_remove: List[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [
                self.time_delta,
                self.characters,
                self.locations,
                self.facts_set,
                self.facts_remove,
                self.flags,
                self.relationships,
                self.arc,
                self.events,
                self.promises_set,
                self.promises_remove,
            ]
        )


class WorldState(BaseModel):
    """世界状态：双模式共用"""

    project_id: str = "demo"
    # 世界时间（从第 1 日 00:00 起算的分钟数）
    time_minutes: int = Field(default=8 * 60)
    precision: Literal["minute", "hour", "day", "scene"] = "minute"
    turn: int = 0
    mode: Literal["game", "director"] = "game"

    characters: Dict[str, CharState] = Field(default_factory=dict)
    locations: Dict[str, LocationState] = Field(default_factory=dict)
    facts: Dict[str, Fact] = Field(default_factory=dict)
    flags: Dict[str, Any] = Field(default_factory=dict)
    relationships: Dict[str, int] = Field(default_factory=dict)

    arc: ArcState = Field(default_factory=ArcState)
    pending_promises: Dict[str, Promise] = Field(default_factory=dict)
    events: List[WorldEvent] = Field(default_factory=list)

    # 导演改写审计（FactOverride 会写在这里，便于回滚）
    overrides: List[Dict[str, Any]] = Field(default_factory=list)

    # ---------------- 构造 ----------------

    @classmethod
    def from_project(
        cls,
        project: NovelProject,
        start_minutes: int = 8 * 60,
        mode: Literal["game", "director"] = "game",
    ) -> "WorldState":
        """从项目资产构建初始世界状态。

        地点与角色默认全部就位：第一个地点作为起点，
        出口由 map mod 在 boot 阶段补全。
        """
        locations: Dict[str, LocationState] = {}
        for loc in project.locations:
            locations[loc.name] = LocationState(
                name=loc.name, description=loc.description
            )
        first = project.locations[0].name if project.locations else "无名之地"
        if first not in locations:
            locations[first] = LocationState(name=first)

        characters: Dict[str, CharState] = {}
        for char in project.characters:
            characters[char.name] = CharState(
                name=char.name, location=first
            )

        facts: Dict[str, Fact] = {}
        for char in project.characters:
            f = Fact(
                subject=char.name,
                predicate="身份",
                object=char.motivation or "未知",
                known_by={char.name, "gm"},
                source_event="boot",
            )
            facts[f.id] = f

        return cls(
            project_id=project.project_id,
            time_minutes=start_minutes,
            mode=mode,
            characters=characters,
            locations=locations,
            facts=facts,
        )

    # ---------------- 查询 ----------------

    def location_of(self, name: str) -> Optional[str]:
        char = self.characters.get(name)
        return char.location if char else None

    def characters_at(self, location: str) -> List[str]:
        return [
            c.name
            for c in self.characters.values()
            if c.location == location and c.status == "active"
        ]

    def present_characters(self) -> List[str]:
        """当前场景可见角色：以玩家（或主角）所在地点为准"""
        if not self.characters:
            return []
        player = self.characters.get("玩家")
        loc = player.location if player else next(iter(self.characters.values())).location
        return self.characters_at(loc)

    def format_time(self) -> str:
        """世界时间 → 人类可读文本"""
        day = self.time_minutes // (24 * 60) + 1
        minutes = self.time_minutes % (24 * 60)
        return f"第{day}日 {minutes // 60:02d}:{minutes % 60:02d}"

    def view(self, agent_id: str) -> Dict[str, Any]:
        """角色视图：只返回该角色能知道的事实与在场信息。

        - 事实按 known_by 过滤（gm / director 全知）；
        - 只返回当前地点与其出口，不泄露未探索地图；
        - 不含其他角色的背包、秘密与信念。
        """
        omniscient = agent_id in ("gm", "director", "narrator")
        actor = self.characters.get(agent_id)
        visible_facts = [
            f.model_dump(mode="json")
            for f in self.facts.values()
            if omniscient or agent_id in f.known_by
        ]

        if omniscient:
            visible_locations = [
                l.model_dump(mode="json") for l in self.locations.values()
            ]
            visible_characters = [
                {
                    "name": c.name,
                    "location": c.location,
                    "emotion": c.emotion,
                    "status": c.status,
                }
                for c in self.characters.values()
            ]
        else:
            loc_name = actor.location if actor else ""
            loc = self.locations.get(loc_name)
            visible_locations = (
                [loc.model_dump(mode="json")] if loc else []
            )
            visible_characters = [
                {
                    "name": c.name,
                    "location": c.location,
                    "emotion": c.emotion,
                    "status": c.status,
                }
                for c in self.characters.values()
                if c.location == loc_name and c.status == "active"
            ]

        return {
            "agent_id": agent_id,
            "time": self.format_time(),
            "time_minutes": self.time_minutes,
            "turn": self.turn,
            "location": actor.location if actor else "",
            "characters": visible_characters,
            "locations": visible_locations,
            "facts": visible_facts,
            "arc": self.arc.model_dump(mode="json"),
            "events": [
                e.model_dump(mode="json") for e in self.events[-5:]
            ],
        }

    # ---------------- 合并 ----------------

    def apply_delta(
        self, delta: "StateDelta | dict", advance_turn: bool = True
    ) -> "WorldState":
        """返回合并后的新状态（不修改原对象）"""
        patch = (
            delta
            if isinstance(delta, StateDelta)
            else StateDelta.model_validate(delta)
        )
        new = self.model_copy(deep=True)
        new.time_minutes = max(0, new.time_minutes + patch.time_delta)
        if advance_turn:
            new.turn += 1

        for name, fields in patch.characters.items():
            target = new.characters.get(name)
            if target is None:
                continue
            for key, value in fields.items():
                if key in CharState.model_fields:
                    setattr(target, key, value)

        for name, fields in patch.locations.items():
            target = new.locations.get(name)
            if target is None:
                continue
            for key, value in fields.items():
                if key in LocationState.model_fields:
                    setattr(target, key, value)

        for fact in patch.facts_set:
            new.facts[fact.id] = fact
        for fid in patch.facts_remove:
            new.facts.pop(fid, None)

        new.flags.update(patch.flags)
        for key, value in patch.relationships.items():
            new.relationships[key] = value
        for key, value in patch.arc.items():
            if key in ArcState.model_fields:
                setattr(new.arc, key, value)

        for promise in patch.promises_set:
            new.pending_promises[promise.promise_id] = promise
        for pid in patch.promises_remove:
            new.pending_promises.pop(pid, None)

        for event in patch.events:
            if event.turn == 0:
                event = event.model_copy(update={"turn": new.turn})
            if event.world_time == 0:
                event = event.model_copy(
                    update={"world_time": new.time_minutes}
                )
            new.events.append(event)

        return new

    def touch(
        self, kind: str, actor: str, summary: str, **data: Any
    ) -> WorldEvent:
        """生成一条当前时刻的事件（不改状态，交给 delta 提交）"""
        return WorldEvent(
            turn=self.turn + 1,
            world_time=self.time_minutes,
            kind=kind,
            actor=actor,
            summary=summary,
            data=data,
        )

    def allowed_actions(self, actor: str) -> List[Dict[str, str]]:
        """地点 + 在场角色 → 可用行动列表（纯查询，不修改状态）。

        输出最多 4 个，按优先级排序：talk > move > wait；
        每项附带确定性 hint（从 state 数据计算，不是 LLM 预估）。
        attack 等低质量或高风险动作不在默认列表里，由 mod 注册追加。
        """
        char = self.characters.get(actor)
        if char is None:
            return []

        actions: List[Dict[str, str]] = []
        loc = self.locations.get(char.location)

        # —— 优先级 1：与在场角色交谈 ——
        for other in self.characters_at(char.location):
            if other == actor:
                continue
            actions.append({
                "kind": "talk",
                "target": other,
                "label": f"和{other}聊聊",
                "hint": "好感可能+1，耗时约 3 分钟",
            })

        # —— 优先级 2：前往相邻地点（带精确耗时）——
        if loc and loc.exits:
            for dest, minutes in loc.exits.items():
                actions.append({
                    "kind": "move",
                    "target": dest,
                    "label": f"前往{dest}",
                    "hint": f"耗时约 {minutes} 分钟",
                })

        # —— 优先级 3：原地等待 ——
        actions.append({
            "kind": "wait",
            "target": "",
            "label": "原地等待",
            "hint": "消耗少量时间",
        })

        return actions[:4]


# ============================================================
# Layer 0 公共协议：裁决与渲染数据类
# 这些是 runtime / memory / crews 各层共享的纯数据定义，
# 统一放 world/state.py 让任何层都能安全 import，
# 避免 runtime 反向 import crews、memory 反向 import runtime。
# ============================================================


class ActionProposal(BaseModel):
    """行动提案：玩家 / NPC / 导演都能提出，GM 来裁定"""

    actor: str
    kind: Literal[
        "move", "attack", "talk", "use", "wait", "observe", "other"
    ] = "other"
    target: Optional[str] = None
    detail: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    source: Literal["player", "npc", "director"] = "player"


class AdjudicationResult(BaseModel):
    """GM 裁决的结构化结果"""

    success: bool
    outcome: str = "ok"
    narrative: str = ""
    state_delta: StateDelta = Field(default_factory=StateDelta)
    error_code: Optional[str] = None
    available: List[str] = Field(default_factory=list)
    quality_flag: Optional[str] = None
    rule: str = ""


DirectiveKind = Literal[
    "say", "show", "hide", "bg", "bgm", "se",
    "wait", "shake", "flash", "cg", "choice",
    "move", "effect", "end",
]


class StageDirective(BaseModel):
    """一条舞台指令（全部可 JSON 序列化）"""

    kind: DirectiveKind
    params: Dict[str, Any] = Field(default_factory=dict)


class StageScene(BaseModel):
    """一次渲染的完整指令序列（也用于 Checkpoint 回放）"""

    directives: List[StageDirective] = Field(default_factory=list)
    text: str = ""
    choices: List[Dict[str, Any]] = Field(default_factory=list)
