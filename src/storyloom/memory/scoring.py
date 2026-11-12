"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

记忆评分与压缩辅助：全部确定性实现，LLM 压缩失败时可降级。
"""

import re
from typing import List

from storyloom.memory.base import MemoryItem

_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]+")
_HIGH_VALUE_WORDS = (
    "伏笔", "秘密", "真相", "死亡", "背叛", "承诺", "契约", "钥匙",
    "地图", "航海图", "血", "爱", "恨", "王", "预言",
)


def summarize(text: str, limit: int = 200) -> str:
    """确定性摘要：取前若干句 + 截断"""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(cleaned) if p.strip()]
    summary = ""
    for part in parts:
        if len(summary) + len(part) > limit:
            break
        summary = f"{summary}；{part}" if summary else part
    if not summary:
        summary = cleaned[:limit]
    if len(cleaned) > len(summary):
        summary += "…"
    return summary[: limit + 1]


def score_importance(
    text: str,
    brief: str = "",
    active_foreshadow: bool = False,
    pinned: bool = False,
) -> float:
    """重要性打分（0.05~1.0），用于决定降级与保留"""
    if pinned:
        return 1.0
    score = 0.35
    if active_foreshadow:
        score += 0.25
    if brief:
        score += 0.1
    hits = sum(1 for word in _HIGH_VALUE_WORDS if word in text)
    score += min(0.3, hits * 0.06)
    length = len(text or "")
    if length >= 400:
        score += 0.1
    elif length <= 40:
        score -= 0.1
    return round(max(0.05, min(1.0, score)), 3)


def score_compressed_importance(text: str, stage: str = "long_term") -> float:
    """压缩产物的留存价值（0.05~1.0）。

    与场景正文打分不同：压缩后的长期记忆已经丢失大量细节，
    只有仍与主线 / 伏笔 / 关键事实相关时才值得常驻，否则应冷却到世界书。
    关键事件条目起点更高，但仍可被创作者设置的阈值冷却。
    """
    score = 0.55 if stage == "key_events" else 0.28
    hits = sum(1 for word in _HIGH_VALUE_WORDS if word in text)
    score += min(0.3 if stage == "key_events" else 0.24, hits * 0.06)
    if any(
        word in text
        for word in ("伏笔", "秘密", "真相", "契约", "承诺", "主线", "目标")
    ):
        score += 0.1
    if len(text) >= 60:
        score += 0.04
    return round(max(0.05, min(1.0, score)), 3)


def compress_batch(
    items: List[MemoryItem], limit: int = 300
) -> str:
    """把一批记忆压成一段确定性文本（LLM 不可用时的兜底）"""
    pieces = []
    for item in items:
        text = item.summary or item.text
        if text:
            pieces.append(text.strip())
    joined = " / ".join(pieces)
    if len(joined) <= limit:
        return joined
    return joined[:limit] + "…"


def should_demote(
    item: MemoryItem,
    current_scene: int,
    importance_threshold: float,
    miss_scenes: int,
) -> bool:
    """长期记忆 / 关键事件是否应降级到检索库（世界书）"""
    if item.tier not in ("long_term", "key_events"):
        return False
    if item.pinned or item.active_foreshadow:
        return False
    if item.importance >= importance_threshold:
        return False
    return (current_scene - item.last_hit_scene) >= miss_scenes
