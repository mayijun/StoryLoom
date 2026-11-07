"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

分层核心记忆：working → short_term → long_term → canon，archive 按需检索。

原则：
- 近期高保真、远期高压缩、冷记忆可召回、再命中可回温；
- 遗忘不是删除：低价值长期记忆降级到检索库；
- 活跃伏笔与 pinned 记忆不降级；
- LLM 压缩失败时走确定性拼接，不阻断生成。
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple

from storyloom.memory.base import (
    MemoryItem,
    MemorySettings,
    TierSpec,
    WorkingMemory,
)
from storyloom.memory.hybrid import HybridBackend
from storyloom.memory.lexical import LexicalBackend
from storyloom.memory.scoring import (
    compress_batch,
    score_importance,
    should_demote,
    summarize,
)
from storyloom.memory.vector import VectorBackend


class LayeredMemory:
    """项目级分层叙事记忆"""

    def __init__(
        self,
        project_id: str,
        repo: Any = None,
        settings: Optional[MemorySettings] = None,
        backend: Optional[str] = None,
        vector: Optional[VectorBackend] = None,
        compress_fn: Optional[Any] = None,
    ):
        self.project_id = project_id
        self.repo = repo
        self.settings = settings or MemorySettings.load()
        self.backend_name = backend or self.settings.backend
        self.compress_fn = compress_fn
        self.working = WorkingMemory()
        self.items: Dict[str, MemoryItem] = {}

        self.lexical = LexicalBackend(repo)
        self.vector = vector or VectorBackend()
        if self.backend_name == "hybrid":
            self._backend: Any = HybridBackend(self.lexical, self.vector)
        elif self.backend_name == "vector":
            self._backend = self.vector
        else:
            self._backend = self.lexical

        self._load()

    # ---------------- 持久化 ----------------

    def _load(self) -> None:
        if self.repo is None:
            return
        prefix = f"{self.project_id}::"
        for row in self.repo.list_memory_items(self.project_id):
            raw_id = row["id"]
            logical_id = (
                raw_id[len(prefix):]
                if raw_id.startswith(prefix)
                else raw_id
            )
            item = MemoryItem.from_row({**row, "id": logical_id})
            self.items[item.id] = item
            if item.tier == "archive":
                self.vector.add(item)

    def _storage_id(self, item_id: str) -> str:
        """存储层 id 带项目前缀，避免跨项目主键冲突"""
        return f"{self.project_id}::{item_id}"

    def _put(self, item: MemoryItem) -> MemoryItem:
        item.project_id = self.project_id
        self.items[item.id] = item
        if self.repo is not None:
            self.repo.upsert_memory_item(
                self.project_id,
                id=self._storage_id(item.id),
                tier=item.tier,
                text=item.text,
                summary=item.summary,
                importance=item.importance,
                pinned=item.pinned,
                scene_index=item.scene_index,
                hits=item.hits,
                adoptions=item.adoptions,
                last_hit_scene=item.last_hit_scene,
                visibility=item.visibility,
                tags=item.tags,
                source=item.source,
                active_foreshadow=item.active_foreshadow,
            )
        if item.tier == "archive":
            self.vector.add(item)
        return item

    def _drop(self, item_id: str) -> None:
        self.items.pop(item_id, None)
        if self.repo is not None:
            self.repo.delete_memory_item(self._storage_id(item_id))
        self.vector.remove(item_id)

    # ---------------- L0 ----------------

    def configure_working(
        self,
        location: str = "",
        present_characters: Optional[List[str]] = None,
        scene_brief: str = "",
        intent: str = "",
        time: str = "",
    ) -> WorkingMemory:
        self.working = WorkingMemory(
            location=location,
            present_characters=list(present_characters or []),
            scene_brief=scene_brief,
            intent=intent,
            time=time,
        )
        return self.working

    # ---------------- L1 写入 ----------------

    def add_scene(
        self,
        scene_index: int,
        prose: str,
        brief: str = "",
        present_characters: Optional[List[str]] = None,
        active_foreshadow: bool = False,
        visibility: str = "public",
        key: Optional[str] = None,
    ) -> MemoryItem:
        """把一个场景写入短期记忆，并触发压缩 / 降级评估"""
        item_id = f"scene:{key or scene_index}"
        text = prose or brief
        summary = summarize(text)
        importance = score_importance(
            text, brief=brief, active_foreshadow=active_foreshadow
        )
        existing = self.items.get(item_id)
        item = MemoryItem(
            id=item_id,
            project_id=self.project_id,
            tier="short_term",
            text=text,
            summary=summary,
            importance=importance,
            scene_index=scene_index,
            visibility=visibility,
            tags=["scene"] + (["active_foreshadow"] if active_foreshadow else []),
            source="scene",
            active_foreshadow=active_foreshadow,
        )
        if existing is not None:
            item.hits = existing.hits
            item.last_hit_scene = existing.last_hit_scene
        self._put(item)
        self.consolidate()
        self.evaluate_demotion(scene_index)
        return item

    def add_archive_item(
        self,
        item_id: str,
        text: str,
        scene_index: int = 0,
        importance: Optional[float] = None,
        tags: Optional[List[str]] = None,
        visibility: str = "public",
        source: str = "asset",
    ) -> MemoryItem:
        """直接写入检索库（资产、历史场景回填、被降级旧记忆）"""
        item = MemoryItem(
            id=item_id,
            project_id=self.project_id,
            tier="archive",
            text=text,
            summary=summarize(text),
            importance=(
                importance
                if importance is not None
                else score_importance(text)
            ),
            scene_index=scene_index,
            visibility=visibility,
            tags=list(tags or []),
            source=source,
        )
        return self._put(item)

    # ---------------- 压缩 ----------------

    def consolidate(self) -> List[MemoryItem]:
        """短期超阈值 → 长期；长期超阈值 → canon；canon 超限 → archive"""
        created: List[MemoryItem] = []

        for spec in self.settings.tiers:
            if spec.compress_into == spec.name:
                continue
            while True:
                layer = self._items_in(spec.name)
                if len(layer) <= spec.max_items:
                    break
                batch_size = max(1, min(spec.compress_batch, len(layer)))
                batch = layer[:batch_size]
                created.append(self._compress(batch, spec))

        if self.settings.canon_compress_into != "canon":
            while True:
                canon_items = self._items_in("canon")
                if len(canon_items) <= self.settings.canon_max_items:
                    break
                overflow = len(canon_items) - self.settings.canon_max_items
                batch = canon_items[: max(1, overflow)]
                created.append(
                    self._compress(
                        batch,
                        TierSpec(
                            name="canon",
                            max_items=self.settings.canon_max_items,
                            compress_batch=len(batch),
                            compress_into=self.settings.canon_compress_into,
                        ),
                    )
                )
        return created

    def _compress(
        self, batch: List[MemoryItem], spec: TierSpec
    ) -> MemoryItem:
        text = compress_batch(batch)
        if self.compress_fn is not None:
            try:
                candidate = str(self.compress_fn(text)).strip()
                if candidate:
                    text = candidate
            except Exception:
                pass
        target = spec.compress_into
        importance = max(item.importance for item in batch)
        tags = sorted(
            {tag for item in batch for tag in item.tags} | {"compressed"}
        )
        item = MemoryItem(
            id=f"mem_{uuid.uuid4().hex[:10]}",
            project_id=self.project_id,
            tier=target,
            text=text,
            summary=text[:200],
            importance=importance,
            # canon 是核心设定，默认 pinned
            pinned=target == "canon",
            scene_index=max(item.scene_index for item in batch),
            visibility="public",
            tags=tags,
            source="compressed",
        )
        for child in batch:
            self._drop(child.id)
        return self._put(item)

    # ---------------- 降级 / 回温 ----------------

    def evaluate_demotion(self, current_scene: int) -> List[MemoryItem]:
        """低价值长期记忆 → 检索库（archive）"""
        demoted: List[MemoryItem] = []
        for item in list(self._items_in("long_term")):
            if should_demote(
                item,
                current_scene=current_scene,
                importance_threshold=self.settings.demotion_threshold,
                miss_scenes=self.settings.demotion_miss_scenes,
            ):
                item.tier = "archive"
                item.source = "demoted"
                item.tags = sorted(set(item.tags) | {"demoted"})
                self._put(item)
                demoted.append(item)
        return demoted

    def _reheat_if_needed(self, item: MemoryItem) -> bool:
        if (
            item.tier == "archive"
            and item.source == "demoted"
            and item.hits >= self.settings.reheat_hits
        ):
            item.tier = "long_term"
            item.source = "reheated"
            item.tags = sorted(set(item.tags) | {"reheated"})
            self._put(item)
            return True
        return False

    # ---------------- 检索 ----------------

    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        viewer: Optional[str] = None,
        current_scene: Optional[int] = None,
    ) -> List[MemoryItem]:
        """按需检索检索库（只含 archive），并记录命中 / 回温"""
        limit = k or self.settings.top_k
        pool = [
            item for item in self._items_in("archive")
            if item.visible_to(viewer)
        ]
        if self.backend_name == "hybrid":
            hits = self._backend.search(
                self.project_id, query, limit=limit, viewer=viewer, pool=pool
            )
        elif self.backend_name == "vector":
            hits = self._backend.search(
                self.project_id, query, limit=limit,
                viewer=viewer, candidates=pool,
            )
        else:
            hits = self._backend.search(
                self.project_id, query, limit=limit, viewer=viewer
            )

        scene = current_scene
        if scene is None:
            scene = max(
                [item.scene_index for item in self.items.values()] or [0]
            )
        result: List[MemoryItem] = []
        for item, _score in hits:
            item.hits += 1
            item.last_hit_scene = scene
            self._put(item)
            if self._reheat_if_needed(item):
                item = self.items[item.id]
            result.append(item)
        return result

    # ---------------- prompt ----------------

    def prompt_block(self, viewer: Optional[str] = None) -> str:
        """核心层（L0 + L1~L3）拼成的 prompt 块；archive 不进 prompt"""
        lines = [self.working.as_prompt_block()]
        labels = {
            "short_term": "近期剧情",
            "long_term": "长期剧情",
            "canon": "核心设定",
        }
        for spec in self.settings.tiers:
            items = [
                item for item in self._items_in(spec.name)
                if item.visible_to(viewer)
            ]
            if not items:
                continue
            lines.append(f"【{labels.get(spec.name, spec.name)}】")
            for item in items:
                lines.append(f"  - {item.summary or item.text}")
        canon = [
            item for item in self._items_in("canon")
            if item.visible_to(viewer) and item.pinned
        ]
        if canon and not any(
            spec.name == "canon" for spec in self.settings.tiers
        ):
            lines.append("【核心设定】")
            for item in canon:
                lines.append(f"  - {item.summary or item.text}")
        return "\n".join(lines)

    def retrieval_block(
        self,
        query: str,
        viewer: Optional[str] = None,
        k: Optional[int] = None,
    ) -> str:
        items = self.retrieve(query, k=k, viewer=viewer)
        if not items:
            return ""
        body = "\n".join(f"  - {item.summary or item.text}" for item in items)
        return f"【相关回忆】\n{body}"

    # ---------------- 工具 ----------------

    def _items_in(self, tier: str) -> List[MemoryItem]:
        items = [item for item in self.items.values() if item.tier == tier]
        items.sort(key=lambda item: (item.scene_index, item.created_at))
        return items

    def counts(self) -> Dict[str, int]:
        result: Dict[str, int] = {
            "working": 1 if self.working.location or self.working.intent else 0
        }
        for tier in ("short_term", "long_term", "canon", "archive"):
            result[tier] = len(self._items_in(tier))
        return result

    def has_scene_memory(self) -> bool:
        return any(
            item.id.startswith("scene:") for item in self.items.values()
        )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "working": self.working.model_dump(mode="json"),
            "items": [
                item.model_dump(mode="json")
                for item in self.items.values()
            ],
            "backend": self.backend_name,
        }

    @classmethod
    def restore(
        cls,
        project_id: str,
        snapshot: Dict[str, Any],
        repo: Any = None,
        settings: Optional[MemorySettings] = None,
        backend: Optional[str] = None,
    ) -> "LayeredMemory":
        """从快照恢复（存档读档 / 重启恢复）"""
        memory = cls(
            project_id=project_id,
            repo=repo,
            settings=settings,
            backend=backend or snapshot.get("backend"),
        )
        memory.items = {}
        for raw in snapshot.get("items", []):
            item = MemoryItem.model_validate(raw)
            memory.items[item.id] = item
        working = snapshot.get("working")
        if working:
            memory.working = WorkingMemory.model_validate(working)
        return memory

    def reset(self) -> None:
        for item_id in list(self.items):
            self._drop(item_id)
        self.items.clear()
        self.working = WorkingMemory()
