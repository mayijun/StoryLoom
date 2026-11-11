"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

记忆层入口：
- 资产模型（角色 / 地点 / 伏笔 / 项目）
- 世界状态（WorldState / Fact / 裁决协议 / 舞台指令）
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
from storyloom.memory.models import (
    CharacterAsset,
    ForeshadowStatus,
    Foreshadowing,
    LocationAsset,
    NovelProject,
    SurpriseProposal,
    SurpriseType,
)
from storyloom.memory.state import (
    ActionProposal,
    AdjudicationResult,
    ArcState,
    CharState,
    Fact,
    FactOverride,
    LocationState,
    Promise,
    StageDirective,
    StageScene,
    StateDelta,
    WorldEvent,
    WorldState,
)
from storyloom.memory.checkpoint import (
    CheckpointRecord,
    CheckpointStore,
    CheckpointSummary,
    SaveRecord,
    SaveService,
    SaveSummary,
    state_from_checkpoint,
    state_from_save,
)
from storyloom.memory.core import LayeredMemory
from storyloom.memory.hybrid import HybridBackend
from storyloom.memory.indexer import MemoryIndexer
from storyloom.memory.legacy import CoreMemory, SimpleRAGMemory
from storyloom.memory.lexical import LexicalBackend
from storyloom.memory.vector import VectorBackend

__all__ = [
    "ActionProposal",
    "AdjudicationResult",
    "ArcState",
    "CharacterAsset",
    "CharState",
    "CheckpointRecord",
    "CheckpointStore",
    "CheckpointSummary",
    "CoreMemory",
    "DemotionRule",
    "Fact",
    "FactOverride",
    "ForeshadowStatus",
    "Foreshadowing",
    "HybridBackend",
    "LayeredMemory",
    "LexicalBackend",
    "LocationAsset",
    "LocationState",
    "MemoryIndexer",
    "MemoryItem",
    "MemorySettings",
    "MemoryTier",
    "NovelProject",
    "Promise",
    "SaveRecord",
    "SaveService",
    "SaveSummary",
    "SimpleRAGMemory",
    "StageDirective",
    "StageScene",
    "StateDelta",
    "SurpriseProposal",
    "SurpriseType",
    "TierSpec",
    "VectorBackend",
    "WorkingMemory",
    "WorldEvent",
    "WorldState",
    "state_from_checkpoint",
    "state_from_save",
]
