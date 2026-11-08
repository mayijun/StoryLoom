"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

记忆层入口：
- 基础版 CoreMemory / SimpleRAGMemory（作者模式继续使用）
- 分层记忆 v2 LayeredMemory + 检索后端 + 历史回填
"""

from storyloom.memory.base import (
    DemotionRule,
    MemoryItem,
    MemorySettings,
    MemoryTier,
    TierSpec,
    WorkingMemory,
)
from storyloom.memory.core import LayeredMemory
from storyloom.memory.hybrid import HybridBackend
from storyloom.memory.indexer import MemoryIndexer
from storyloom.memory.legacy import CoreMemory, SimpleRAGMemory
from storyloom.memory.lexical import LexicalBackend
from storyloom.memory.vector import VectorBackend

__all__ = [
    "CoreMemory",
    "DemotionRule",
    "HybridBackend",
    "LayeredMemory",
    "LexicalBackend",
    "MemoryIndexer",
    "MemoryItem",
    "MemorySettings",
    "MemoryTier",
    "SimpleRAGMemory",
    "TierSpec",
    "VectorBackend",
    "WorkingMemory",
]
