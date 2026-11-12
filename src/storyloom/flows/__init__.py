"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

Backward-compat shim: 旧的 storyloom.flows.scene_flow / turn_flow 模块
已合并进 storyloom.engine.narrative。这里 re-export 常用符号，
让旧代码的 import 路径不需要修改也能工作。
"""

# ── scene_flow.py 里搬来的函数 ──
from storyloom.engine.narrative import (
    advance_scene_counters,
    apply_foreshadow_ops,
    parse_json_block,
)

# ── turn_flow.py 里搬来的数据类 ──
from storyloom.engine.narrative import TurnBoot, TurnResult

# ── narrative 主类 ──
from storyloom.engine.narrative import NarrativeEngine

__all__ = [
    "advance_scene_counters",
    "apply_foreshadow_ops",
    "parse_json_block",
    "TurnBoot",
    "TurnResult",
    "NarrativeEngine",
]
