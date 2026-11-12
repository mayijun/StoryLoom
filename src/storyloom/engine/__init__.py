"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

Narrative Engine：双模式统一叙事引擎 + 统一世界推进。

合并前的 SceneGenerationFlow（scene_flow.py）和 TurnLoop（turn_flow.py）
全部搬到这里。一个类，两个公开入口，内部共享 narrate + advance_world。
"""

from storyloom.engine.narrative import (
    AdvanceResult,
    NarrateResult,
    NarrativeEngine,
    SceneResult,
    TurnBoot,
    TurnResult,
)

__all__ = [
    "AdvanceResult",
    "NarrateResult",
    "NarrativeEngine",
    "SceneResult",
    "TurnBoot",
    "TurnResult",
]
