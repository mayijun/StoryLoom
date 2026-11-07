"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

混合检索：FTS + 向量，RRF 融合；向量不可用时自动退化为 FTS。
"""

from typing import List, Optional, Tuple

from storyloom.memory.base import MemoryItem
from storyloom.memory.lexical import LexicalBackend
from storyloom.memory.vector import VectorBackend

RRF_K = 60


class HybridBackend:
    name = "hybrid"

    def __init__(
        self, lexical: LexicalBackend, vector: VectorBackend
    ):
        self.lexical = lexical
        self.vector = vector
        self.available = True

    def search(
        self,
        project_id: str,
        query: str,
        limit: int = 5,
        viewer: Optional[str] = None,
        pool: Optional[List[MemoryItem]] = None,
    ) -> List[Tuple[MemoryItem, float]]:
        lexical_hits = self.lexical.search(
            project_id, query, limit=limit, viewer=viewer
        )
        if not self.vector.available:
            return lexical_hits

        vector_hits = self.vector.search(
            project_id, query, limit=limit, viewer=viewer, candidates=pool
        )
        if not vector_hits:
            return lexical_hits

        fused: dict[str, Tuple[MemoryItem, float]] = {}
        for rank, (item, _) in enumerate(lexical_hits):
            fused[item.id] = (item, 1.0 / (RRF_K + rank + 1))
        for rank, (item, _) in enumerate(vector_hits):
            prev = fused.get(item.id)
            score = 1.0 / (RRF_K + rank + 1)
            if prev:
                fused[item.id] = (prev[0], prev[1] + score)
            else:
                fused[item.id] = (item, score)
        merged = sorted(
            fused.values(), key=lambda pair: pair[1], reverse=True
        )
        return merged[:limit]
