"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

输入总线：玩家意图与意图路由。

设计纪律：
- 意图解析是确定性的（关键词 + 地图/在场角色匹配），不交给 LLM；
- 选项（choice）与自由输入（text）走同一条解析与裁决链；
- 解析只产出 ActionProposal，不直接改状态。
"""

import re
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from storyloom.world.state import ActionProposal, WorldState


class PlayerIntent(BaseModel):
    """玩家输入：自由文本、选项、点击、跳过、存读档等"""

    kind: Literal[
        "text", "choice", "click", "qte", "skip", "save", "load", "meta"
    ] = "text"
    payload: Dict[str, object] = Field(default_factory=dict)


class InterpretedIntent(BaseModel):
    """路由后的意图：进入 interpret_player_action / interpret_director_command"""

    mode: Literal["player_action", "director_command", "idle", "meta"] = (
        "player_action"
    )
    proposals: List[ActionProposal] = Field(default_factory=list)
    raw: str = ""
    scene_goal: str = ""
    meta_action: Optional[str] = None

    def primary(self) -> Optional[ActionProposal]:
        return self.proposals[0] if self.proposals else None


_MOVE_VERBS = (
    "前往", "走到", "来到", "进入", "回到", "赶往", "动身去", "去", "到",
)
_ATTACK_WORDS = (
    "攻击", "袭击", "拔剑", "刺向", "刺杀", "杀死", "砍", "偷袭",
    "殴打", "打斗", "打倒", "打伤", "打架",
)
_REST_WORDS = ("打坐", "练功", "修炼", "冥想", "调息", "运功")
_TALK_WORDS = ("交谈", "聊", "问", "说", "告诉", "喊道", "搭话", "回应")
_LOOK_WORDS = ("观察", "环顾", "打量", "看看")
_WAIT_WORDS = ("等待", "等等", "原地等", "休息")
_USE_WORDS = ("使用", "拿出", "掏出", "翻开")
_SAVE_WORDS = ("存档", "保存进度")
_LOAD_WORDS = ("读档", "载入存档")


def _contains_any(text: str, words) -> bool:
    return any(word in text for word in words)


class IntentRouter:
    """确定性意图路由"""

    def route(
        self, intent: PlayerIntent, state: WorldState, actor: str = "玩家"
    ) -> InterpretedIntent:
        if intent.kind in ("save", "load", "meta"):
            return InterpretedIntent(
                mode="meta",
                raw=str(intent.payload.get("text", "")),
                meta_action=intent.kind,
            )
        if intent.kind == "skip":
            return InterpretedIntent(mode="idle", raw="")

        if intent.kind in ("choice", "click"):
            # Agent 推荐行动只携带自然语言 text，与手动输入走同一套解析。
            # 旧的规则选项仍可通过 action/kind + target 直接构造提案。
            text = str(intent.payload.get("text", "")).strip()
            if text:
                proposals = self._parse_text(text, state, actor)
                if not proposals:
                    proposals = [
                        ActionProposal(
                            actor=actor,
                            kind="other",
                            detail=text,
                            source="player",
                        )
                    ]
                return InterpretedIntent(
                    mode="player_action", proposals=proposals, raw=text
                )
            proposal = self._from_payload(intent.payload, actor)
            if proposal is None:
                return InterpretedIntent(mode="idle", raw="")
            return InterpretedIntent(
                mode="player_action",
                proposals=[proposal],
                raw=str(intent.payload.get("label", "")),
            )

        text = str(intent.payload.get("text", "")).strip()
        if not text:
            return InterpretedIntent(mode="idle", raw="")

        if state.mode == "director":
            return InterpretedIntent(
                mode="director_command",
                proposals=[
                    ActionProposal(
                        actor=actor,
                        kind="other",
                        detail=text,
                        source="director",
                    )
                ],
                raw=text,
                scene_goal=text,
            )

        proposals = self._parse_text(text, state, actor)
        if not proposals:
            proposals = [
                ActionProposal(
                    actor=actor, kind="other", detail=text, source="player"
                )
            ]
            return InterpretedIntent(
                mode="player_action", proposals=proposals, raw=text
            )
        return InterpretedIntent(
            mode="player_action", proposals=proposals, raw=text
        )

    # ---------------- 文本解析 ----------------

    def _parse_text(
        self, text: str, state: WorldState, actor: str
    ) -> List[ActionProposal]:
        proposals: List[ActionProposal] = []

        if _contains_any(text, _SAVE_WORDS):
            return []
        if _contains_any(text, _LOAD_WORDS):
            return []

        location = self._match_location(text, state)
        character = self._match_character(text, state, actor)

        if _contains_any(text, _ATTACK_WORDS):
            target = character
            if target is None:
                present = [
                    n for n in state.characters_at(
                        state.characters[actor].location
                    )
                    if n != actor
                ]
                target = present[0] if present else None
            proposals.append(
                ActionProposal(
                    actor=actor,
                    kind="attack",
                    target=target,
                    detail=text,
                    source="player",
                )
            )
            return proposals

        if _contains_any(text, _TALK_WORDS):
            proposals.append(
                ActionProposal(
                    actor=actor,
                    kind="talk",
                    target=character,
                    detail=text,
                    source="player",
                )
            )
            return proposals

        # 「回到住处打坐练功」这类休整描述优先按等待处理，避免被移动动词抢走
        if _contains_any(text, _REST_WORDS) and location is None:
            proposals.append(
                ActionProposal(
                    actor=actor, kind="wait", detail=text, source="player"
                )
            )
            return proposals

        if location is not None or _contains_any(text, _MOVE_VERBS):
            target = location or self._strip_move_verbs(text)
            proposals.append(
                ActionProposal(
                    actor=actor,
                    kind="move",
                    target=target,
                    detail=text,
                    source="player",
                )
            )
            return proposals

        if _contains_any(text, _LOOK_WORDS):
            proposals.append(
                ActionProposal(
                    actor=actor, kind="observe", detail=text, source="player"
                )
            )
            return proposals

        if _contains_any(text, _WAIT_WORDS):
            proposals.append(
                ActionProposal(
                    actor=actor, kind="wait", detail=text, source="player"
                )
            )
            return proposals

        if _contains_any(text, _USE_WORDS):
            proposals.append(
                ActionProposal(
                    actor=actor,
                    kind="use",
                    target=character,
                    detail=text,
                    source="player",
                )
            )
            return proposals

        return []

    def _from_payload(
        self, payload: Dict[str, object], actor: str
    ) -> Optional[ActionProposal]:
        kind = str(payload.get("action") or payload.get("kind") or "").strip()
        if not kind:
            if payload.get("text"):
                # 选项里也可以直接给自由文本
                return ActionProposal(
                    actor=actor,
                    kind="other",
                    detail=str(payload["text"]),
                    source="player",
                )
            return None
        if kind not in {
            "move", "attack", "talk", "use", "wait", "observe", "other"
        }:
            kind = "other"
        return ActionProposal(
            actor=actor,
            kind=kind,  # type: ignore[arg-type]
            target=str(payload.get("target") or "") or None,
            detail=str(payload.get("text") or payload.get("label") or ""),
            params={
                k: v for k, v in payload.items()
                if k not in ("action", "kind", "target", "text", "label")
            },
            source="player",
        )

    # ---------------- 匹配工具 ----------------

    @staticmethod
    def _match_location(text: str, state: WorldState) -> Optional[str]:
        for name in state.locations:
            if name in text:
                return name
        return None

    @staticmethod
    def _match_character(
        text: str, state: WorldState, actor: str
    ) -> Optional[str]:
        for name in state.characters:
            if name != actor and name in text:
                return name
        return None

    @staticmethod
    def _strip_move_verbs(text: str) -> str:
        cleaned = text
        for verb in _MOVE_VERBS:
            cleaned = cleaned.replace(verb, " ")
        cleaned = re.sub(r"[，。！？,.!?\s]+", "", cleaned)
        return cleaned or text


__all__ = ["IntentRouter", "InterpretedIntent", "PlayerIntent"]
