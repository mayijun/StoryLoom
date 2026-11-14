"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

向量检索后端：可选。没有显式 embedding 时不可用，
上层（hybrid / core）自动降级，不阻断生成。
"""

import math
from typing import Callable, Dict, List, Optional, Tuple

from storyloom.memory.base import MemoryItem

EmbeddingFn = Callable[[str], List[float]]


class VectorBackend:
    """轻量向量后端（内存索引 + 可注入 embedding）

    不默认绑定 embedding 模型；中文叙事必须显式配置多语言模型。
    """

    name = "vector"

    def __init__(self, embedding_fn: Optional[EmbeddingFn] = None):
        self.embedding_fn = embedding_fn
        self.available = embedding_fn is not None
        self._vectors: Dict[str, List[float]] = {}

    def add(self, item: MemoryItem) -> None:
        if not self.available:
            return
        text = item.summary or item.text
        if not text:
            return
        try:
            self._vectors[item.id] = self.embedding_fn(text)  # type: ignore[misc]
        except Exception:
            self.available = False
            self._vectors.clear()

    def remove(self, item_id: str) -> None:
        self._vectors.pop(item_id, None)

    def search(
        self,
        project_id: str,
        query: str,
        limit: int = 5,
        viewer: Optional[str] = None,
        candidates: Optional[List[MemoryItem]] = None,
    ) -> List[Tuple[MemoryItem, float]]:
        if not self.available or not query:
            return []
        try:
            query_vec = self.embedding_fn(query)  # type: ignore[misc]
        except Exception:
            return []
        pool = candidates or []
        scored: List[Tuple[MemoryItem, float]] = []
        for item in pool:
            if not item.is_visible_to(viewer):
                continue
            vec = self._vectors.get(item.id)
            if vec is None:
                self.add(item)
                vec = self._vectors.get(item.id)
            if vec is None:
                continue
            scored.append((item, _cosine(query_vec, vec)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
