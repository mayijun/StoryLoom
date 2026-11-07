"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

词法检索后端（默认）：专名 / 伏笔 / 场景回溯。

实现为 SQLite 友好的确定性打分：
- 完整查询命中权重最高；
- 中文按二元组拆词，兼容「航海图」这类专名；
- 无 FTS5 扩展时同样可用，索引可随时重建。
"""

import re
from typing import List, Optional, Tuple

from storyloom.memory.base import MemoryItem

_WORD = re.compile(r"[A-Za-z0-9_]+")


def query_terms(query: str) -> List[str]:
    q = (query or "").strip().lower()
    if not q:
        return []
    terms = list(_WORD.findall(q))
    cjk = "".join(ch for ch in q if "\u4e00" <= ch <= "\u9fff")
    for i in range(len(cjk) - 1):
        terms.append(cjk[i: i + 2])
    if cjk and cjk not in terms:
        terms.append(cjk)
    if q not in terms:
        terms.append(q)
    return terms


def score_text(query: str, text: str) -> float:
    q = (query or "").strip().lower()
    body = (text or "").lower()
    if not q or not body:
        return 0.0
    score = 0.0
    if q in body:
        score += 10.0
    for term in query_terms(q):
        if term and term in body:
            score += 1.0 if len(term) > 1 else 0.3
    return score


class LexicalBackend:
    """f 后端：从检索库（archive）中按词法相关性召回"""

    name = "fts"

    def __init__(self, repo):
        self.repo = repo
        self.available = repo is not None

    def search(
        self,
        project_id: str,
        query: str,
        limit: int = 5,
        viewer: Optional[str] = None,
        tiers: Tuple[str, ...] = ("archive",),
    ) -> List[Tuple[MemoryItem, float]]:
        if not self.available:
            return []
        rows = self.repo.list_memory_items(project_id)
        scored: List[Tuple[MemoryItem, float]] = []
        prefix = f"{project_id}::"
        for row in rows:
            if row["tier"] not in tiers:
                continue
            item = MemoryItem.from_row(
                {
                    **row,
                    "id": (
                        row["id"][len(prefix):]
                        if row["id"].startswith(prefix)
                        else row["id"]
                    ),
                }
            )
            if not item.visible_to(viewer):
                continue
            body = " ".join(
                [item.text, item.summary, " ".join(item.tags)]
            )
            score = score_text(query, body)
            if score > 0:
                scored.append((item, score))
        scored.sort(key=lambda pair: (-pair[1], -pair[0].scene_index))
        return scored[:limit]
