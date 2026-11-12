"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

分层核心记忆：working → short_term → long_term → key_events，archive 按需检索。

原则：
- 近期高保真、远期高压缩、冷记忆可召回、再命中可回温；
- 遗忘不是删除：低价值长期记忆降级到检索库；
- 活跃伏笔与 pinned 记忆不降级；
- LLM 压缩失败时走确定性拼接，不阻断生成。
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple

from storyloom.memory.base import (
    CROWD_VIEWER,
    PUBLIC_VIEWERS,
    MemoryItem,
    MemorySettings,
    MemoryVisibility,
    TierSpec,
    WorkingMemory,
)
from storyloom.memory.compress import (
    build_compress_prompt,
    clamp_compressed_text,
    fallback_compress,
    is_empty_compression,
)
from storyloom.memory.hybrid import HybridBackend
from storyloom.memory.lexical import LexicalBackend
from storyloom.memory.scoring import (
    score_compressed_importance,
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
            item = self._normalize_loaded(
                MemoryItem.from_row({**row, "id": logical_id})
            )
            self.items[item.id] = item
            if item.tier == "archive":
                self.vector.add(item)

    @staticmethod
    def _normalize_loaded(item: MemoryItem) -> MemoryItem:
        """旧版压缩产物不再由系统 pin，重要度按当前规则重算，
        否则旧存档里的关键事件永远无法按创作者阈值冷却。"""
        if item.tier == "key_events" and item.source == "compressed":
            item.pinned = False
            item.importance = score_compressed_importance(
                item.text, stage="key_events"
            )
        return item

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
                known_by=item.known_by,
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
        known_by: Optional[List[str]] = None,
        crowd: bool = False,
        key: Optional[str] = None,
    ) -> MemoryItem:
        """把一个场景写入短期记忆，并触发压缩 / 降级评估。

        ``known_by`` 缺省时用 ``present_characters`` 作为目击者集合；
        两者都未提供时视为公开叙述。``crowd=True`` 表示有未具名路人见证。
        """
        item_id = f"scene:{key or scene_index}"
        scope = known_by if known_by is not None else present_characters
        explicit_scope = scope is not None
        witnesses = sorted({name for name in (scope or []) if name})
        if crowd:
            witnesses = sorted(set(witnesses) | {CROWD_VIEWER})
            explicit_scope = True
        if PUBLIC_VIEWERS.intersection(witnesses):
            visibility: MemoryVisibility = "public"
            witnesses = []
        else:
            visibility = "restricted" if explicit_scope else "public"
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
            known_by=witnesses,
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
        visibility: MemoryVisibility = "public",
        known_by: Optional[List[str]] = None,
        source: str = "asset",
    ) -> MemoryItem:
        """直接写入检索库（资产、历史场景回填、被降级旧记忆）"""
        witnesses = sorted({name for name in (known_by or []) if name})
        if PUBLIC_VIEWERS.intersection(witnesses):
            visibility = "public"
            witnesses = []
        elif witnesses:
            visibility = "restricted"
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
            known_by=witnesses,
            tags=list(tags or []),
            source=source,
        )
        return self._put(item)

    # ---------------- 伏笔投影 ----------------

    def sync_foreshadowings(self, foreshadowings: List[Any]) -> List[MemoryItem]:
        """把伏笔描述与真相投影成 archive 记忆条目。

        两者共享同一 scope：默认 restricted + []（仅全知视角可见）；
        创建时指定 known_by 的角色可见（例如某个配角天生知道）。
        已存在的条目取 known_by 并集，保留后续“某人得知真相”的更新。
        """
        keep: set[str] = set()
        touched: List[MemoryItem] = []

        for fs in foreshadowings:
            fid = fs.foreshadow_id
            initial = {
                name for name in (getattr(fs, "known_by", None) or []) if name
            }
            base_visibility = getattr(fs, "visibility", "restricted")
            entries = [
                (f"foreshadow:{fid}", fs.description, ["foreshadow", "clue"]),
            ]
            truth = (getattr(fs, "target_revelation", "") or "").strip()
            if truth:
                entries.append(
                    (
                        f"foreshadow_truth:{fid}",
                        truth,
                        ["foreshadow", "truth"],
                    )
                )

            for item_id, content, tags in entries:
                keep.add(item_id)
                existing = self.items.get(item_id)
                merged = sorted(initial | set(existing.known_by if existing else []))
                if base_visibility == "public" or PUBLIC_VIEWERS.intersection(
                    merged
                ):
                    visibility: MemoryVisibility = "public"
                    merged = []
                else:
                    visibility = "restricted"

                if (
                    existing is not None
                    and existing.text == content
                    and existing.visibility == visibility
                    and sorted(existing.known_by) == merged
                ):
                    touched.append(existing)
                    continue
                if existing is None:
                    touched.append(
                        self.add_archive_item(
                            item_id,
                            content,
                            tags=tags,
                            visibility=visibility,
                            known_by=merged,
                            source="foreshadow",
                        )
                    )
                    continue
                existing.text = content
                existing.summary = summarize(content)
                existing.visibility = visibility
                existing.known_by = merged
                existing.tags = list(tags)
                existing.source = "foreshadow"
                self._put(existing)
                touched.append(existing)

        for item in list(self.items.values()):
            if item.source == "foreshadow" and item.id not in keep:
                self._drop(item.id)
        return touched

    # ---------------- 世界状态投影 ----------------

    def sync_world_state(
        self, state: Any, current_scene: Optional[int] = None
    ) -> List[MemoryItem]:
        """把 WorldState 的回忆型投影写入记忆层。

        权威真相仍由 WorldState 持有；这里只维护可供召回的记忆视图。
        已冷却到世界书的条目保持在世界书，不因每回合同步而复活。
        """
        scene = state.turn if current_scene is None else current_scene
        projection = state.memory_projection()
        keep = {raw["id"] for raw in projection}
        touched: List[MemoryItem] = []

        for raw in projection:
            existing = self.items.get(raw["id"])
            visibility = raw.get("visibility", "public")
            known_by = sorted(raw.get("known_by") or [])
            if (
                existing is not None
                and existing.text == raw["text"]
                and existing.visibility == visibility
                and sorted(existing.known_by) == known_by
            ):
                continue
            tier = raw["tier"]
            if existing is not None and existing.tier not in (
                "long_term", "key_events"
            ):
                tier = existing.tier  # 已降级 / 归档的条目保持原位
            item = MemoryItem(
                id=raw["id"],
                project_id=self.project_id,
                tier=tier,
                text=raw["text"],
                summary=summarize(raw["text"]),
                importance=raw.get("importance", 0.5),
                scene_index=scene,
                last_hit_scene=scene,
                visibility=visibility,
                known_by=known_by,
                tags=list(raw.get("tags", [])),
                source="world_state",
            )
            if existing is not None:
                item.hits = existing.hits
                item.adoptions = existing.adoptions
            touched.append(self._put(item))

        for item in list(self.items.values()):
            if item.source == "world_state" and item.id not in keep:
                self._drop(item.id)
        # 生命周期（压缩 / 降级）交给下一次 add_scene 统一处理，
        # 避免每回合同步都触发一次压缩抖动。
        return touched

    # ---------------- 压缩 ----------------

    def consolidate(self) -> List[MemoryItem]:
        """短期超阈值 → 长期；长期超阈值 → 关键事件；关键事件溢出在层内合并"""
        created: List[MemoryItem] = []

        for spec in self.settings.tiers:
            if spec.compress_into == spec.name:
                continue
            while True:
                layer = self._items_in(spec.name)
                if len(layer) <= spec.max_items:
                    break
                batch = self._pick_compress_batch(
                    layer, spec.compress_batch
                )
                item = self._compress(batch, spec)
                if item is not None:
                    created.append(item)

        if self.settings.key_events_compress_into == "archive":
            # 兼容旧配置：关键事件溢出写入检索库
            while True:
                key_items = self._items_in("key_events")
                if len(key_items) <= self.settings.key_events_max_items:
                    break
                overflow = (
                    len(key_items) - self.settings.key_events_max_items
                )
                batch = key_items[: max(1, overflow)]
                item = self._compress(
                    batch,
                    TierSpec(
                        name="key_events",
                        max_items=self.settings.key_events_max_items,
                        compress_batch=len(batch),
                        compress_into="archive",
                        compress_max_chars=(
                            self.settings.key_events_compress_max_chars
                        ),
                        compress_hint=(
                            self.settings.key_events_compress_hint
                        ),
                    ),
                )
                if item is not None:
                    created.append(item)
        else:
            created.extend(self._merge_key_events_overflow())
        return created

    def _merge_key_events_overflow(self) -> List[MemoryItem]:
        """关键事件溢出时合并最旧事件；没有关键事件就丢弃，不污染世界书。"""
        created: List[MemoryItem] = []
        if self.settings.key_events_max_items <= 0:
            return created
        while True:
            key_items = self._items_in("key_events")
            if len(key_items) <= self.settings.key_events_max_items:
                break
            overflow = len(key_items) - self.settings.key_events_max_items
            batch_size = max(1, overflow)
            # 只溢出 1 条时，与次旧条目一起合并，保证层数确实下降
            if batch_size == 1 and len(key_items) >= 2:
                batch_size = 2
            batch = self._pick_compress_batch(key_items, batch_size)
            item = self._compress(
                batch,
                TierSpec(
                    name="key_events",
                    max_items=self.settings.key_events_max_items,
                    compress_batch=batch_size,
                    compress_into="key_events",
                    compress_max_chars=(
                        self.settings.key_events_compress_max_chars
                    ),
                    compress_hint=self.settings.key_events_compress_hint,
                ),
            )
            if item is not None:
                created.append(item)
        return created

    @staticmethod
    def _pick_compress_batch(
        layer: List[MemoryItem], batch_size: int
    ) -> List[MemoryItem]:
        """按可见范围分组选取压缩批次，避免把不同知情者的记忆混在一起。"""
        groups: Dict[Tuple[str, Tuple[str, ...]], List[MemoryItem]] = {}
        for item in layer:
            key = (item.visibility, tuple(sorted(item.known_by)))
            groups.setdefault(key, []).append(item)
        size = max(1, batch_size)
        for items in groups.values():
            if len(items) >= 2:
                return items[:size]
        # 所有分组都只有 1 条：只能跨组合并，由 _scope_for_batch 取交集
        return layer[: max(1, min(size, len(layer)))]

    @staticmethod
    def _scope_for_batch(
        batch: List[MemoryItem],
    ) -> Tuple[MemoryVisibility, List[str]]:
        """压缩后的可见范围：公开才公开，否则取各来源 known_by 的交集。"""
        if any(item.visibility == "public" for item in batch):
            return "public", []
        if not batch:
            return "public", []
        known = set(batch[0].known_by)
        for item in batch[1:]:
            known &= set(item.known_by)
        if PUBLIC_VIEWERS.intersection(known):
            return "public", []
        return "restricted", sorted(known)

    def _compress(
        self, batch: List[MemoryItem], spec: TierSpec
    ) -> Optional[MemoryItem]:
        """把一批记忆压缩到目标层；关键事件层没有可保留事件时返回 None。"""
        target = spec.compress_into
        max_chars = spec.compress_max_chars
        prompt = build_compress_prompt(
            target,
            batch,
            max_chars=max_chars,
            hint=spec.compress_hint,
        )

        text = ""
        if self.compress_fn is not None:
            try:
                candidate = str(self.compress_fn(prompt)).strip()
                if candidate and not is_empty_compression(candidate, target):
                    text = candidate
            except Exception:
                text = ""
        if not text:
            text = fallback_compress(batch, target, max_chars=max_chars)
        text = clamp_compressed_text(
            text, max_chars, multiline=(target == "key_events")
        )

        for child in batch:
            self._drop(child.id)
        if not text:
            return None

        visibility, known_by = self._scope_for_batch(batch)
        last_scene = max(item.scene_index for item in batch)
        item = MemoryItem(
            id=f"mem_{uuid.uuid4().hex[:10]}",
            project_id=self.project_id,
            tier=target,
            text=text,
            summary=text[:200],
            importance=score_compressed_importance(text, stage=target),
            # 关键事件也可按创作者配置的阈值冷却到世界书，因此默认不 pin
            pinned=False,
            scene_index=last_scene,
            # 刚压缩产生的记忆从当前场景开始计算冷却，避免立即降级
            last_hit_scene=last_scene,
            visibility=visibility,
            known_by=known_by,
            tags=sorted({"compressed", target}),
            source="compressed",
            active_foreshadow=any(item.active_foreshadow for item in batch),
        )
        return self._put(item)

    # ---------------- 降级 / 回温 ----------------

    def evaluate_demotion(self, current_scene: int) -> List[MemoryItem]:
        """低价值长期记忆 / 关键事件 → 检索库（archive）

        每一层使用创作者配置的降级规则（settings.rule_for），
        因此长期记忆与关键事件可以有不同的重要度阈值和沉睡场景数。
        """
        demoted: List[MemoryItem] = []
        for tier in ("long_term", "key_events"):
            rule = self.settings.rule_for(tier)
            for item in list(self._items_in(tier)):
                if should_demote(
                    item,
                    current_scene=current_scene,
                    importance_threshold=rule.importance_threshold,
                    miss_scenes=rule.miss_scenes,
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
                self.project_id, query, limit=limit,
                viewer=viewer, candidates=pool,
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
        """核心层（当前场景 + L1~L3）拼成的 prompt 块；archive 不进 prompt"""
        lines = [self.working.as_prompt_block()]
        labels = {
            "short_term": "近期剧情",
            "long_term": "长期剧情",
            "key_events": "关键事件",
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
                body = (
                    item.text
                    if spec.name == "key_events"
                    else (item.summary or item.text)
                )
                lines.append(f"  - {body}")
        key_events = [
            item for item in self._items_in("key_events")
            if item.visible_to(viewer)
        ]
        if key_events and not any(
            spec.name == "key_events" for spec in self.settings.tiers
        ):
            lines.append("【关键事件】")
            for item in key_events:
                lines.append(f"  - {item.text}")
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
        body = "\n".join(
            f"  - {item.summary or item.text}" for item in items
        )
        return f"【相关回忆】\n{body}"

    # ---------------- 工具 ----------------

    def _items_in(self, tier: str) -> List[MemoryItem]:
        items = [item for item in self.items.values() if item.tier == tier]
        items.sort(key=lambda item: (item.scene_index, item.created_at))
        return items

    def counts(self) -> Dict[str, int]:
        """核心记忆只统计持久化三层 + 世界书；当前场景不作为一个记忆层。"""
        result: Dict[str, int] = {}
        for tier in ("short_term", "long_term", "key_events", "archive"):
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
        compress_fn: Optional[Any] = None,
    ) -> "LayeredMemory":
        """从快照恢复（存档读档 / 重启恢复）"""
        memory = cls(
            project_id=project_id,
            repo=repo,
            settings=settings,
            backend=backend or snapshot.get("backend"),
            compress_fn=compress_fn,
        )
        memory.items = {}
        for raw in snapshot.get("items", []):
            item = cls._normalize_loaded(
                MemoryItem.model_validate(raw)
            )
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
