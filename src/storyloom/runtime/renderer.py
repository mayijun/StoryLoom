"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

表现层：把裁决结果转成舞台指令与文本。

TextAdapter 是 M0 唯一的适配器；ADV / NVL / 3D 未来只需新增
PresentationAdapter，不修改渲染器与 Flow。
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional

from storyloom.runtime.directive import StageDirective, StageScene
from storyloom.world.state import AdjudicationResult, WorldState


class TextAdapter:
    """把 StageDirective 序列适配成前端可直接消费的文本消息"""

    def render(self, scene: StageScene) -> Dict[str, Any]:
        blocks: List[Dict[str, Any]] = []
        for directive in scene.directives:
            if directive.kind == "say":
                blocks.append(
                    {"type": "say", "text": directive.params.get("text", "")}
                )
            elif directive.kind == "choice":
                blocks.append(
                    {
                        "type": "choice",
                        "options": directive.params.get("options", []),
                    }
                )
            elif directive.kind in ("bg", "show", "move"):
                blocks.append(
                    {
                        "type": "scene",
                        "kind": directive.kind,
                        **directive.params,
                    }
                )
            else:
                blocks.append(
                    {"type": "effect", "kind": directive.kind, **directive.params}
                )
        return {
            "text": scene.text,
            "blocks": blocks,
            "choices": scene.choices,
        }


class SceneRenderer:
    """确定性渲染器 + 可选 LLM 润色。

    LLM 不可用时（无 Key / 超时 / 抛错）自动退回确定性文本，
    游戏模式零交互，不阻塞玩家。
    """

    def __init__(
        self,
        prose_fn: Optional[Callable[[str, WorldState], str]] = None,
    ):
        self.prose_fn = prose_fn
        self.adapter = TextAdapter()

    # ---------------- 公共入口 ----------------

    def render(
        self,
        state_before: WorldState,
        state_after: WorldState,
        adjudication: AdjudicationResult,
        actor: str = "玩家",
        prose: Optional[str] = None,
        suggested_actions: Optional[List[Dict[str, str]]] = None,
    ) -> StageScene:
        return self._build(
            state_before,
            state_after,
            adjudication,
            actor,
            prose,
            suggested_actions=suggested_actions,
        )

    async def arender(
        self,
        state_before: WorldState,
        state_after: WorldState,
        adjudication: AdjudicationResult,
        actor: str = "玩家",
        context: str = "",
        style: str = "",
        description: str = "",
        world_book: str = "",
    ) -> StageScene:
        prose = await self._maybe_prose(
            adjudication, state_after, context,
            style=style, description=description, world_book=world_book,
        )
        return self._build(
            state_before, state_after, adjudication, actor, prose
        )

    async def _maybe_prose(
        self,
        adjudication: AdjudicationResult,
        state: WorldState,
        context: str = "",
        style: str = "",
        description: str = "",
        world_book: str = "",
    ) -> Optional[str]:
        if self.prose_fn is None:
            return None
        prompt = self.prompt_for(
            adjudication, state, context,
            style=style, description=description, world_book=world_book,
        )
        try:
            result = await asyncio.to_thread(self.prose_fn, prompt, state)
            text = str(result).strip()
            return text or None
        except Exception:
            return None

    # ---------------- 组装 ----------------

    def prompt_for(
        self,
        adjudication: AdjudicationResult,
        state: WorldState,
        context: str = "",
        style: str = "",
        description: str = "",
        world_book: str = "",
    ) -> str:
        lines = [
            "请把下面的世界事件改写成第二人称、克制而有画面感的中文叙事，"
            "不要新增未经裁决的事实，不要复述系统提示。",
            "世界先于主角：NPC 有各自的目标与处境，不会因为玩家期待而改变；"
            "不要替玩家做决定，不要自动让玩家成功。",
        ]
        if style:
            lines.append(f"文风：{style}")
        if description:
            lines.append(f"作品设定：{description}")
        if world_book:
            lines.append("")
            lines.append("## 世界书（只作事实与线索，不要直接说出秘密）")
            lines.append(world_book)
        if context:
            lines.append("")
            lines.append("## 你已知的剧情与设定（仅作上下文，不必逐字引用）")
            lines.append(context)
        lines.extend(
            [
                "",
                f"时间：{state.format_time()}",
                f"地点：{self._actor_location(state)}",
                f"裁决：{adjudication.outcome}",
                f"事实：{adjudication.narrative}",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _actor_location(state: WorldState) -> str:
        player = state.characters.get("玩家")
        if player:
            return player.location
        if state.characters:
            return next(iter(state.characters.values())).location
        return ""

    def _build(
        self,
        state_before: WorldState,
        state_after: WorldState,
        adjudication: AdjudicationResult,
        actor: str,
        prose: Optional[str],
        suggested_actions: Optional[List[Dict[str, str]]] = None,
    ) -> StageScene:
        directives: List[StageDirective] = []
        location = self._actor_location(state_after)

        moved = state_before.characters.get(actor) and (
            state_before.characters[actor].location != location
        )
        if moved:
            directives.append(
                StageDirective(
                    kind="move",
                    params={
                        "from": state_before.characters[actor].location,
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

        text = (prose or adjudication.narrative or "").strip()
        if text:
            directives.append(StageDirective(kind="say", params={"text": text}))

        if not adjudication.success:
            directives.append(
                StageDirective(
                    kind="effect",
                    params={
                        "name": "blocked",
                        "error_code": adjudication.error_code or adjudication.outcome,
                        "available": adjudication.available,
                    },
                )
            )

        choices: List[Dict[str, Any]] = []
        # Agent 建议只是自然语言快捷输入，不构成行动白名单；
        # 点击后由 IntentRouter 按自由文本解析，GM 仍负责实际裁决。
        for item in (suggested_actions or [])[:4]:
            action_text = str(
                item.get("text") or item.get("label") or ""
            ).strip()
            if not action_text:
                continue
            choices.append(
                {
                    "index": len(choices),
                    "label": action_text,
                    "text": action_text,
                    "hint": item.get("hint", ""),
                    "source": "agent",
                }
            )

        # LLM 不可用、旧配置仍输出纯文本或建议为空时，保留确定性兜底。
        if not choices:
            options = state_after.allowed_actions(actor)
            choices = [
                {
                    "index": i,
                    "label": item["label"],
                    "action": item["kind"],
                    "target": item["target"],
                    "hint": item.get("hint", ""),
                    "source": "rules",
                }
                for i, item in enumerate(options[:4])
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

        return StageScene(
            directives=directives,
            text=text,
            choices=choices,
        )


__all__ = ["SceneRenderer", "TextAdapter"]
