"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

输出总线：舞台指令。

渲染层产出指令序列，PresentationAdapter 决定怎么演。
文本只是 say 的一种表现；ADV / NVL / 3D 消费同一串指令。
"""

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

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
    """一次渲染的完整指令序列"""

    directives: List[StageDirective] = Field(default_factory=list)
    text: str = ""
    choices: List[Dict[str, Any]] = Field(default_factory=list)


__all__ = ["DirectiveKind", "StageDirective", "StageScene"]
