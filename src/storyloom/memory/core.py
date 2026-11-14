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

import re
import threading
import uuid
import warnings
from typing import Any, Dict, List, Optional, Tuple

from storyloom.memory.base import (
    CROWD_VIEWER,
    MEMORY_ITEM_MAX_CHARS,
    MemoryItem,
    MemorySettings,
    TierSpec,
    WorkingMemory,
    normalize_visible_to,
)
from storyloom.memory.compress import (
    build_compress_prompt,
    clamp_compressed_text,
    fallback_compress,
    is_empty_compression,
    parse_compressed_output,
)
from storyloom.memory.hybrid import HybridBackend
from storyloom.memory.lexical import LexicalBackend, score_text
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
        # 后台回填线程与请求线程可能同时增删条目，读快照/写入统一加锁
        self._lock = threading.RLock()
        # 检索命中计数先记在内存，回合末合并落库，避免每次召回都写一次
        self._pending_hits: Dict[str, MemoryItem] = {}
        # 检索缓存：版本号随条目变化递增；archive 池与打分结果按版本复用
        self._version = 0
        self._archive_pool_cache: Optional[List[MemoryItem]] = None
        self._hits_cache: Dict[
            Tuple[str, Optional[str], int], List[Tuple[MemoryItem, float]]
        ] = {}

        self.lexical = LexicalBackend(repo)
        self.vector = vector or VectorBackend()
        if self.backend_name == "hybrid":
            self._backend: Any = HybridBackend(self.lexical, self.vector)
        elif self.backend_name == "vector":
            self._backend = self.vector
        else:
            self._backend = self.lexical

        self.backend_degraded = (
            self.backend_name in ("vector", "hybrid")
            and not self.vector.available
        )
        if self.backend_degraded:
            fallback = (
                "hybrid 退化为词法检索"
                if self.backend_name == "hybrid"
                else "vector 召回为空"
            )
            warnings.warn(
                f"记忆后端 {self.backend_name} 未注入 embedding，{fallback}",
                RuntimeWarning,
                stacklevel=2,
            )

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
                _prompt_text(item), stage="key_events"
            )
        return item

    def _storage_id(self, item_id: str) -> str:
        """存储层 id 带项目前缀，避免跨项目主键冲突"""
        return f"{self.project_id}::{item_id}"

    def _all_items(self) -> List[MemoryItem]:
        """条目快照：后台回填与请求线程并发时避免迭代中字典被修改。"""
        with self._lock:
            return list(self.items.values())

    def _bump_version_locked(self) -> None:
        """条目发生变化：递增版本并失效检索缓存。"""
        self._version += 1
        self._archive_pool_cache = None
        self._hits_cache.clear()

    def _archive_pool(self) -> List[MemoryItem]:
        """检索库条目池；同版本内复用，避免每次召回都全量重扫。"""
        with self._lock:
            if self._archive_pool_cache is None:
                self._archive_pool_cache = [
                    item for item in self.items.values()
                    if item.tier == "archive"
                    # 异步侧台的待推进请求是流程状态，不进入世界书检索
                    and item.source != "side_stage_pending"
                ]
            return list(self._archive_pool_cache)

    def _persist(self, item: MemoryItem) -> None:
        """把单条记忆写入仓储；不触碰向量索引。"""
        if self.repo is None:
            return
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
            visible_to=item.visible_to,
            tags=item.tags,
            source=item.source,
            active_foreshadow=item.active_foreshadow,
        )

    def _put(self, item: MemoryItem) -> MemoryItem:
        item.project_id = self.project_id
        with self._lock:
            self.items[item.id] = item
            self._pending_hits.pop(item.id, None)
            self._bump_version_locked()
        self._persist(item)
        if item.tier == "archive":
            self.vector.add(item)
        return item

    def _flush_pending_hits(self) -> None:
        """回合末合并写入检索命中计数（不重复计算 archive 的 embedding）。"""
        with self._lock:
            if not self._pending_hits:
                return
            pending = list(self._pending_hits.values())
            self._pending_hits.clear()
        for item in pending:
            self._persist(item)

    def _drop(self, item_id: str) -> None:
        with self._lock:
            self.items.pop(item_id, None)
            self._pending_hits.pop(item_id, None)
            self._bump_version_locked()
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
        visible_to: Optional[List[str]] = None,
        crowd: bool = False,
        key: Optional[str] = None,
    ) -> MemoryItem:
        """把一个场景写入短期记忆，并触发压缩 / 降级评估。

        ``visible_to`` 缺省时用 ``present_characters`` 作为目击者集合；
        两者都未提供时视为公开叙述。``crowd=True`` 表示有未具名路人见证。

        写入前会对 prose 做确定性摘要（默认 200 字），摘要本身不应超过
        ``MEMORY_ITEM_MAX_CHARS``。完整 prose 永远**不**直接入库——
        如果 Agent 在 ``memory_facts`` 里附带了预压缩事实，narrative 会
        优先用 ``add_condensed`` 写入目标层，本函数作为短期事实的兜底入口。
        """
        self._flush_pending_hits()
        item_id = f"scene:{key or scene_index}"
        scope = (
            visible_to if visible_to is not None else present_characters
        )
        explicit_scope = scope is not None
        witnesses = sorted({name for name in (scope or []) if name})
        if crowd:
            witnesses = sorted(set(witnesses) | {CROWD_VIEWER})
            explicit_scope = True
        visible_to = (
            normalize_visible_to(visible_to=witnesses, default_public=False)
            if explicit_scope
            else ["all"]
        )
        text = prose or brief
        summary = summarize(text)
        _warn_if_oversize(summary, "add_scene → short_term")
        importance = score_importance(
            text, brief=brief, active_foreshadow=active_foreshadow
        )
        existing = self.items.get(item_id)
        item = MemoryItem(
            id=item_id,
            project_id=self.project_id,
            tier="short_term",
            text=summary,
            summary=summary,
            importance=importance,
            scene_index=scene_index,
            visible_to=visible_to,
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
        visible_to: Optional[List[str]] = None,
        source: str = "asset",
    ) -> MemoryItem:
        """直接写入检索库（资产、历史场景回填、被降级旧记忆）

        调用方应保证 text 不超过 ``MEMORY_ITEM_MAX_CHARS``；超过时
        只打 warning，不拆分也不截断。
        """
        _warn_if_oversize(text, f"add_archive_item {item_id}")
        scope = (
            ["all"]
            if visible_to is None
            else normalize_visible_to(
                visible_to=visible_to, default_public=False
            )
        )
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
            visible_to=scope,
            tags=list(tags or []),
            source=source,
        )
        return self._put(item)

    def add_condensed(
        self,
        tier: str,
        text: str,
        *,
        scene_index: int = 0,
        visible_to: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[float] = None,
        source: str = "agent_memory_fact",
        display_text: Optional[str] = None,
        consolidate: bool = True,
    ) -> MemoryItem:
        """写入已经由 Agent 压缩好的记忆事实。

        支持全部四层：short_term（压缩摘要）、long_term（压缩产物）、
        key_events（关键事件）、archive（世界书/资产）。

        与 ``add_scene`` 不同，这里不再等待阈值触发压缩：材料本身
        就是压缩产物，直接落到目标层；随后仍受该层容量与降级规则约束。

        ``text`` 是存储版本；``display_text`` 是给玩家/导演看的白话版本。
        文言存储时调用方必须提供 ``display_text``，否则摘要也会是文言。
        调用方应保证 text 不超过 ``MEMORY_ITEM_MAX_CHARS``；超过时
        只打 warning，不拆分也不截断。

        批量写入同一回合的多条 fact 时传 ``consolidate=False``，
        由调用方在循环结束后统一整理一次，避免每条 fact 重复压缩。
        """
        self._flush_pending_hits()
        if tier not in ("short_term", "long_term", "key_events", "archive"):
            raise ValueError(f"不支持的目标层: {tier}")
        _warn_if_oversize(text, f"add_condensed → {tier}")
        display = (display_text or "").strip()
        if display and display != text:
            tags = sorted(set(tags or []) | {"classical_storage"})
        else:
            tags = sorted(set(tags or []))
        # Agent 省略 visible_to 或传空列表表示公开；非空列表才受限。
        scope = (
            normalize_visible_to(
                visible_to=visible_to, default_public=False
            )
            if visible_to
            else ["all"]
        )

        if tier == "archive":
            item_id = f"arch_{uuid.uuid4().hex[:10]}"
        else:
            item_id = f"cond_{uuid.uuid4().hex[:10]}"

        item = MemoryItem(
            id=item_id,
            project_id=self.project_id,
            tier=tier,
            text=text,
            summary=display or summarize(text),
            importance=(
                importance
                if importance is not None
                else (
                    score_compressed_importance(
                        display or text, stage=tier
                    )
                    if tier in ("long_term", "key_events")
                    else score_importance(display or text)
                )
            ),
            pinned=False,
            scene_index=scene_index,
            # 刚写入的压缩记忆从当前场景开始冷却，避免立即降级
            last_hit_scene=scene_index,
            visible_to=scope,
            tags=tags,
            source=source,
        )
        self._put(item)
        if consolidate and tier in ("short_term", "long_term", "key_events"):
            self.consolidate()
        return item

    # ---------------- 伏笔投影 ----------------

    def sync_foreshadowings(self, foreshadowings: List[Any]) -> List[MemoryItem]:
        """把伏笔描述与真相投影成 archive 记忆条目。

        两者共享同一 scope：默认 []（仅全知视角可见）；
        创建时指定 visible_to 的角色可见（例如某个配角天生知道）。
        已存在的条目取 visible_to 并集，保留后续“某人得知真相”的更新。
        """
        keep: set[str] = set()
        touched: List[MemoryItem] = []

        for fs in foreshadowings:
            fid = fs.foreshadow_id
            initial = {
                name
                for name in (getattr(fs, "visible_to", None) or [])
                if name
            }
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
                merged = sorted(
                    initial | set(existing.visible_to if existing else [])
                )
                scope = normalize_visible_to(
                    visible_to=merged, default_public=False
                )

                if (
                    existing is not None
                    and existing.text == content
                    and existing.visible_to == scope
                ):
                    touched.append(existing)
                    continue
                if existing is None:
                    touched.append(
                        self.add_archive_item(
                            item_id,
                            content,
                            tags=tags,
                            visible_to=scope,
                            source="foreshadow",
                        )
                    )
                    continue
                existing.text = content
                existing.summary = summarize(content)
                existing.visible_to = scope
                existing.tags = list(tags)
                existing.source = "foreshadow"
                self._put(existing)
                touched.append(existing)

        for item in self._all_items():
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
            visible_to = normalize_visible_to(
                visible_to=raw.get("visible_to"),
                default_public=True,
            )
            raw_text = raw["text"]
            _warn_if_oversize(raw_text, f"sync_world_state → {raw['id']}")
            if (
                existing is not None
                and existing.text == raw_text
                and existing.visible_to == visible_to
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
                text=raw_text,
                summary=summarize(raw_text),
                importance=raw.get("importance", 0.5),
                scene_index=scene,
                last_hit_scene=scene,
                visible_to=visible_to,
                tags=list(raw.get("tags", [])),
                source="world_state",
            )
            if existing is not None:
                item.hits = existing.hits
                item.adoptions = existing.adoptions
            touched.append(self._put(item))

        for item in self._all_items():
            if item.source == "world_state" and item.id not in keep:
                self._drop(item.id)
        # 生命周期（压缩 / 降级）交给下一次 add_scene 统一处理，
        # 避免每回合同步都触发一次压缩抖动。
        return touched

    # ---------------- 压缩 ----------------

    def consolidate(self) -> List[MemoryItem]:
        """短期超阈值 → 长期；长期超阈值 → 关键事件；关键事件无损冷却。"""
        changed: List[MemoryItem] = []

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
                if batch is None:
                    # 没有同可见范围的同伴：不跨组合并，单条无损降级。
                    if not self._demote_oldest_unprotected(layer):
                        break
                    continue
                item = self._compress(batch, spec)
                if item is None:
                    break
                changed.append(item)

        changed.extend(self._cool_key_events_overflow())
        return changed

    def _demote_oldest_unprotected(
        self, layer: List[MemoryItem]
    ) -> bool:
        """把最旧的非受保护条目原样迁入 archive；不改变文本与可见范围。"""
        for item in layer:
            if item.pinned or item.active_foreshadow:
                continue
            item.tier = "archive"
            item.source = "demoted"
            item.tags = sorted(set(item.tags) | {"demoted", "no_peer"})
            self._put(item)
            return True
        return False

    def _cool_key_events_overflow(self) -> List[MemoryItem]:
        """把最冷的关键事件原样迁入世界书，不压缩、合并或丢弃。"""
        key_items = self._items_in("key_events")
        capacity = max(0, self.settings.key_events_max_items)
        overflow = len(key_items) - capacity
        if overflow <= 0:
            return []

        candidates = [
            item for item in key_items
            if not item.pinned and not item.active_foreshadow
        ]
        if not candidates:
            # 显式常驻与活跃伏笔优先；受保护事件允许暂时超过容量。
            return []

        recent_texts = [
            self.working.intent,
            self.working.scene_brief,
            *(
                item.summary or item.text
                for item in (
                    self._items_in("short_term") + self._items_in("long_term")
                )
            ),
        ]
        recent_context = "\n".join(text for text in recent_texts if text)
        lexical_scores = {
            item.id: score_text(
                recent_context,
                " ".join([item.text, item.summary, " ".join(item.tags)]),
            )
            for item in candidates
        }

        vector_scores: Dict[str, float] = {}
        if recent_context and self.vector.available:
            # 关键事件可被 WorldState 原地更新，评分前刷新文本对应的向量。
            for item in candidates:
                self.vector.remove(item.id)
                self.vector.add(item)
            vector_scores = {
                item.id: score
                for item, score in self.vector.search(
                    self.project_id,
                    recent_context,
                    limit=len(candidates),
                    viewer="director",
                    candidates=candidates,
                )
            }
        # 向量覆盖全部候选时以语义相关性为主、词法命中为辅；
        # embedding 不可用或失败时，全部候选统一退回词法相关性。
        use_vector = len(vector_scores) == len(candidates)

        def heat(item: MemoryItem) -> Tuple[Any, ...]:
            if use_vector:
                relevance = vector_scores[item.id]
                lexical_tiebreak = lexical_scores[item.id]
            else:
                relevance = lexical_scores[item.id]
                lexical_tiebreak = 0.0
            return (
                relevance,
                lexical_tiebreak,
                item.hits,
                item.adoptions,
                item.last_hit_scene,
                item.scene_index,
                item.created_at,
                item.id,
            )

        candidates.sort(key=heat)
        cooled: List[MemoryItem] = []
        for item in candidates[:overflow]:
            item.tier = "archive"
            item.source = "demoted"
            item.tags = sorted(
                set(item.tags) | {"demoted", "key_event_overflow"}
            )
            self._put(item)
            cooled.append(item)
        return cooled

    @staticmethod
    def _pick_compress_batch(
        layer: List[MemoryItem], batch_size: int
    ) -> Optional[List[MemoryItem]]:
        """只在完全相同的 ``visible_to`` 分组内选压缩批次，绝不跨组。"""
        groups: Dict[Tuple[str, ...], List[MemoryItem]] = {}
        for item in layer:
            groups.setdefault(tuple(item.visible_to), []).append(item)
        candidates = [items for items in groups.values() if len(items) >= 2]
        if not candidates:
            return None
        # 优先压缩条目最多的组；同规模时取更旧的一组，保证行为确定。
        candidates.sort(
            key=lambda items: (
                -len(items),
                items[0].scene_index,
                items[0].created_at,
            )
        )
        size = max(1, batch_size)
        return candidates[0][:size]

    def _compress(
        self, batch: List[MemoryItem], spec: TierSpec
    ) -> Optional[MemoryItem]:
        """把一批记忆压缩到目标层；关键事件层没有可保留事件时返回 None。"""
        target = spec.compress_into
        max_chars = spec.compress_max_chars
        classical = self.settings.classical_compression
        prompt = build_compress_prompt(
            target,
            batch,
            max_chars=max_chars,
            hint=spec.compress_hint,
            classical=classical,
        )

        scope = list(batch[0].visible_to) if batch else ["all"]

        text = ""
        display = ""
        paired = False
        if self.compress_fn is not None:
            try:
                candidate = str(self.compress_fn(prompt, scope)).strip()
                if candidate:
                    text, display, paired = parse_compressed_output(
                        candidate, classical=classical
                    )
                    if is_empty_compression(text, target):
                        text, display, paired = "", "", False
            except Exception:
                text, display, paired = "", "", False
        if not text:
            # 无法取得成对的白话展示版时不启用文言，保证展示面可读。
            text = fallback_compress(batch, target, max_chars=max_chars)
            display = text
            paired = False
        text = clamp_compressed_text(
            text, max_chars, multiline=(target == "key_events")
        )
        display = clamp_compressed_text(
            display or text, MEMORY_ITEM_MAX_CHARS
        )
        if not text:
            return None

        for child in batch:
            self._drop(child.id)

        last_scene = max(item.scene_index for item in batch)
        tags = {"compressed", target}
        if paired:
            tags.add("classical_storage")
        item = MemoryItem(
            id=f"mem_{uuid.uuid4().hex[:10]}",
            project_id=self.project_id,
            tier=target,
            text=text,
            summary=display,
            importance=score_compressed_importance(display, stage=target),
            # 关键事件也可按创作者配置的阈值冷却到世界书，因此默认不 pin
            pinned=False,
            scene_index=last_scene,
            # 刚压缩产生的记忆从当前场景开始计算冷却，避免立即降级
            last_hit_scene=last_scene,
            visible_to=scope,
            tags=sorted(tags),
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
            item.tier = (
                "key_events"
                if "key_event_overflow" in item.tags
                else "long_term"
            )
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
        if not (query or "").strip():
            return []
        pool = self._archive_pool()
        if not pool:
            return []

        # 无 embedding 时打分与 viewer 无关，按查询缓存"全量排序结果"，
        # 不同 viewer 复用同一份打分，只做可见性过滤。
        shared = not self.vector.available
        cache_key = (
            self._version,
            query,
            None if shared else viewer,
            limit if not shared else 0,
        )
        hits = self._hits_cache.get(cache_key)
        if hits is None:
            if shared:
                # 用全知视角打分，避免受限条目在打分层就被过滤掉
                hits = self._backend_search(
                    query, len(pool), "director", pool
                )
            else:
                hits = self._backend_search(query, limit, viewer, pool)
            if len(self._hits_cache) >= 64:
                self._hits_cache.clear()
            self._hits_cache[cache_key] = hits
        elif not shared:
            hits = list(hits)
        if shared:
            hits = [
                pair for pair in hits if pair[0].is_visible_to(viewer)
            ][:limit]

        scene = current_scene
        if scene is None:
            scene = max(
                [item.scene_index for item in self._all_items()] or [0]
            )
        result: List[MemoryItem] = []
        for item, _score in hits:
            item.hits += 1
            item.last_hit_scene = scene
            # 命中计数先记内存，回合末由 _flush_pending_hits 合并落库
            with self._lock:
                self._pending_hits[item.id] = item
            if self._reheat_if_needed(item):
                item = self.items[item.id]
            result.append(item)
        return result

    def _backend_search(
        self,
        query: str,
        limit: int,
        viewer: Optional[str],
        pool: List[MemoryItem],
    ) -> List[Tuple[MemoryItem, float]]:
        if self.backend_name == "hybrid":
            return self._backend.search(
                self.project_id, query, limit=limit, viewer=viewer, pool=pool
            )
        return self._backend.search(
            self.project_id, query, limit=limit, viewer=viewer, candidates=pool
        )

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
                if item.is_visible_to(viewer)
            ]
            if not items:
                continue
            lines.append(f"【{labels.get(spec.name, spec.name)}】")
            for item in items:
                body = _prompt_text(item)
                lines.append(f"  - {body}")
        key_events = [
            item for item in self._items_in("key_events")
            if item.is_visible_to(viewer)
        ]
        if key_events and not any(
            spec.name == "key_events" for spec in self.settings.tiers
        ):
            lines.append("【关键事件】")
            for item in key_events:
                lines.append(f"  - {_prompt_text(item)}")
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
        items = [item for item in self._all_items() if item.tier == tier]
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
            item.id.startswith("scene:") for item in self._all_items()
        )

    def snapshot(self) -> Dict[str, Any]:
        self._flush_pending_hits()
        return {
            "working": self.working.model_dump(mode="json"),
            "items": [
                item.model_dump(mode="json")
                for item in self._all_items()
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


# ---------------------------------------------------------------------------
# 模块级辅助
# ---------------------------------------------------------------------------

def _prompt_text(item: MemoryItem) -> str:
    """给玩家 / 导演 / Agent prompt 的展示文本。

    文言存储条目取 ``summary``（白话展示版）；旧数据没有双轨时保持
    原有行为：关键事件用全文，其他层优先用摘要。
    """
    if "classical_storage" in item.tags:
        return item.summary or item.text
    if item.tier == "key_events":
        return item.text
    return item.summary or item.text


def _warn_if_oversize(text: str, caller: str) -> None:
    """写入前的长度软校验：超过 MEMORY_ITEM_MAX_CHARS 时打 warning。

    不拆分、不截断、不阻断——让调用方在运行时看到 warning，意识到
    自己输出了超长内容，进而在生产端修复（例如让 Agent 在 JSON
    的 memory_facts 里输出预压缩版本）。
    """
    if not text:
        return
    if len(text) > MEMORY_ITEM_MAX_CHARS:
        warnings.warn(
            f"[memory] {caller}: 文本长度 {len(text)} > "
            f"MEMORY_ITEM_MAX_CHARS ({MEMORY_ITEM_MAX_CHARS}). "
            f"不拆分不截断，调用方应在源头压缩。",
            stacklevel=2,
        )
