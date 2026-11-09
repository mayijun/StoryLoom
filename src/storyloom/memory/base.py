"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

分层记忆的基础数据结构与层配置。
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field

MemoryTier = Literal["working", "short_term", "long_term", "canon", "archive"]

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "memory_config.default.yaml"


class MemoryItem(BaseModel):
    """一条叙事记忆（核心层或检索库）"""

    id: str
    project_id: str = ""
    tier: MemoryTier = "short_term"
    text: str = ""
    summary: str = ""
    importance: float = 0.5
    pinned: bool = False

    scene_index: int = 0
    hits: int = 0
    adoptions: int = 0
    last_hit_scene: int = 0

    # public / private:<角色名>
    visibility: str = "public"
    tags: List[str] = Field(default_factory=list)
    source: str = "scene"
    active_foreshadow: bool = False

    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def visible_to(self, viewer: Optional[str]) -> bool:
        if self.visibility == "public":
            return True
        if not viewer:
            return False
        return self.visibility == f"private:{viewer}"

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "MemoryItem":
        return cls(
            id=row["id"],
            project_id=row.get("project_id", ""),
            tier=row.get("tier", "short_term"),
            text=row.get("text", ""),
            summary=row.get("summary", ""),
            importance=row.get("importance", 0.5),
            pinned=row.get("pinned", False),
            scene_index=row.get("scene_index", 0),
            hits=row.get("hits", 0),
            adoptions=row.get("adoptions", 0),
            last_hit_scene=row.get("last_hit_scene", 0),
            visibility=row.get("visibility", "public"),
            tags=list(row.get("tags") or []),
            source=row.get("source", "scene"),
            active_foreshadow=row.get("active_foreshadow", False),
            created_at=row.get("created_at") or datetime.now(timezone.utc).isoformat(),
        )


class TierSpec(BaseModel):
    """一层核心记忆的容量与压缩策略"""

    name: MemoryTier
    max_items: int = 6
    compress_batch: int = 3
    compress_into: MemoryTier = "long_term"
    compress_max_chars: int = 200
    compress_hint: str = ""


class DemotionRule(BaseModel):
    """一层核心记忆的冷却规则（由创作者配置）"""

    importance_threshold: float = 0.35
    miss_scenes: int = 10


class MemorySettings(BaseModel):
    """memory_config.default.yaml 的运行时视图"""

    tiers: List[TierSpec] = Field(default_factory=list)
    canon_max_items: int = 20
    # 正史溢出时默认在正史内部合并，不再写入世界书
    canon_compress_into: MemoryTier = "canon"
    canon_compress_max_chars: int = 240
    canon_compress_hint: str = ""
    # 兼容旧配置的全局降级参数
    demotion_threshold: float = 0.35
    demotion_miss_scenes: int = 10
    # 按层配置的降级阈值：长期记忆与历史事件都可以冷却到世界书
    # 留空时回落到全局 demotion_threshold / demotion_miss_scenes
    demotion_rules: Dict[str, DemotionRule] = Field(default_factory=dict)
    reheat_hits: int = 2
    backend: Literal["fts", "vector", "hybrid"] = "fts"
    top_k: int = 5

    def rule_for(self, tier: str) -> DemotionRule:
        rule = self.demotion_rules.get(tier)
        if rule is not None:
            return rule
        return DemotionRule(
            importance_threshold=self.demotion_threshold,
            miss_scenes=self.demotion_miss_scenes,
        )

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "MemorySettings":
        """从配置字典构建（YAML 文件与数据库 payload 共用同一结构）"""
        raw = raw or {}
        tiers = [
            TierSpec.model_validate(item)
            for item in raw.get("tiers", [])
        ]
        canon = raw.get("canon", {})
        demotion = raw.get("demotion", {}) or {}
        retrieval = raw.get("retrieval", {})
        legacy_threshold = float(
            demotion.get("importance_threshold", 0.35)
        )
        legacy_miss = int(demotion.get("miss_scenes", 10))
        long_rule_raw = demotion.get("long_term", {}) or {}
        canon_rule_raw = demotion.get("canon", {}) or {}
        demotion_rules = {
            "long_term": DemotionRule(
                importance_threshold=float(
                    long_rule_raw.get(
                        "importance_threshold", legacy_threshold
                    )
                ),
                miss_scenes=int(
                    long_rule_raw.get("miss_scenes", legacy_miss)
                ),
            ),
            "canon": DemotionRule(
                importance_threshold=float(
                    canon_rule_raw.get("importance_threshold", 0.30)
                ),
                miss_scenes=int(
                    canon_rule_raw.get("miss_scenes", 20)
                ),
            ),
        }
        return cls(
            tiers=tiers,
            canon_max_items=int(canon.get("max_items", 20)),
            canon_compress_into=canon.get("compress_into", "canon"),
            canon_compress_max_chars=int(
                canon.get("compress_max_chars", 240)
            ),
            canon_compress_hint=str(canon.get("compress_hint", "")),
            demotion_threshold=legacy_threshold,
            demotion_miss_scenes=legacy_miss,
            demotion_rules=demotion_rules,
            reheat_hits=int(demotion.get("reheat_hits", 2)),
            backend=retrieval.get("backend", "fts"),
            top_k=int(retrieval.get("top_k", 5)),
        )

    def to_dict(self) -> Dict[str, Any]:
        """导出为 YAML / 数据库使用的配置结构"""
        return {
            "tiers": [spec.model_dump() for spec in self.tiers],
            "canon": {
                "max_items": self.canon_max_items,
                "compress_into": self.canon_compress_into,
                "compress_max_chars": self.canon_compress_max_chars,
                "compress_hint": self.canon_compress_hint,
            },
            "demotion": {
                **{
                    tier: rule.model_dump()
                    for tier, rule in self.demotion_rules.items()
                },
                "importance_threshold": self.demotion_threshold,
                "miss_scenes": self.demotion_miss_scenes,
                "reheat_hits": self.reheat_hits,
            },
            "retrieval": {"backend": self.backend, "top_k": self.top_k},
        }

    @classmethod
    def load(cls, path: Optional[str] = None) -> "MemorySettings":
        target = Path(path) if path else CONFIG_PATH
        if not target.exists():
            return cls(
                tiers=[
                    TierSpec(
                        name="short_term", max_items=6,
                        compress_batch=3, compress_into="long_term",
                        compress_max_chars=220,
                    ),
                    TierSpec(
                        name="long_term", max_items=8,
                        compress_batch=4, compress_into="canon",
                        compress_max_chars=160,
                    ),
                ]
            )
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return cls.from_dict(raw)


class WorkingMemory(BaseModel):
    """L0：当前场景状态，总是进入 prompt，不持久化"""

    location: str = ""
    present_characters: List[str] = Field(default_factory=list)
    scene_brief: str = ""
    intent: str = ""
    time: str = ""

    def as_prompt_block(self) -> str:
        return (
            f"【当前场景】地点: {self.location or '未知'}；"
            f"时间: {self.time or '未知'}；"
            f"在场角色: {', '.join(self.present_characters) or '无'}\n"
            f"【本轮意图】{self.intent or self.scene_brief or '（无）'}"
        )
