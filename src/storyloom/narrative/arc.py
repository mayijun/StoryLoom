"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

叙事节拍：起承转合 + 张力目标 + 信息预算。

M0 使用确定性策略，接口预留给 M1 的 TFC 动态计算。
"""

from typing import List

from pydantic import BaseModel, Field

from storyloom.world.state import ArcState, WorldState

_PHASE_TENSION = {
    "setup": 0.25,
    "rising": 0.5,
    "climax": 0.85,
    "resolution": 0.3,
}
_PHASE_BEATS = {
    "setup": 3,
    "rising": 4,
    "climax": 2,
    "resolution": 2,
}
_PHASE_NEXT = {
    "setup": "rising",
    "rising": "climax",
    "climax": "resolution",
    "resolution": "setup",
}


class DirectorFrame(BaseModel):
    """送给演员与渲染层的导演帧"""

    phase: str = "setup"
    tension_target: float = 0.3
    beats_remaining: int = 4
    info_budget: float = 1.0
    goal: str = ""
    hints: List[str] = Field(default_factory=list)


class ArcDirector:
    """确定性节拍推进"""

    def frame(self, state: WorldState, goal: str = "") -> DirectorFrame:
        arc = state.arc
        hints = [
            f"当前节拍：{arc.phase}",
            f"张力目标：{arc.tension_target:.2f}",
            f"剩余节拍：{arc.beats_remaining}",
        ]
        if arc.info_budget < 0.3:
            hints.append("信息预算偏低：本回合应少揭露、多铺垫")
        if arc.phase == "climax":
            hints.append("高潮段：冲突必须正面发生")
        return DirectorFrame(
            phase=arc.phase,
            tension_target=arc.tension_target,
            beats_remaining=arc.beats_remaining,
            info_budget=arc.info_budget,
            goal=goal,
            hints=hints,
        )

    def advance(
        self,
        state: WorldState,
        success: bool = True,
        dramatic: bool = False,
    ) -> ArcState:
        """推进一个节拍；返回新的 ArcState（不改原状态）"""
        arc = state.arc.model_copy(deep=True)
        arc.beats_remaining -= 1
        if dramatic:
            arc.tension_target = min(1.0, arc.tension_target + 0.08)
        elif success:
            arc.tension_target = min(
                1.0, arc.tension_target + 0.02
            )
        arc.info_budget = max(0.0, round(arc.info_budget - 0.12, 3))

        if arc.beats_remaining <= 0:
            arc.phase = _PHASE_NEXT[arc.phase]  # type: ignore[assignment]
            arc.beats_remaining = _PHASE_BEATS[arc.phase]
            arc.tension_target = _PHASE_TENSION[arc.phase]
            arc.info_budget = 1.0
        return arc


__all__ = ["ArcDirector", "DirectorFrame"]
