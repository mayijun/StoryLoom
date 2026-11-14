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


def score_terms(query: str, terms: List[str], text: str) -> float:
    """用预先拆好的查询词打分，避免对每个条目重复拆词。"""
    q = (query or "").strip().lower()
    body = (text or "").lower()
    if not q or not body:
        return 0.0
    score = 0.0
    if q in body:
        score += 10.0
    for term in terms:
        if term and term in body:
            score += 1.0 if len(term) > 1 else 0.3
    return score


def score_text(query: str, text: str) -> float:
    q = (query or "").strip().lower()
    return score_terms(q, query_terms(q), text)


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
        candidates: Optional[List[MemoryItem]] = None,
    ) -> List[Tuple[MemoryItem, float]]:
        if not self.available:
            return []
        if candidates is not None:
            items = [item for item in candidates if item.tier in tiers]
        else:
            rows = self.repo.list_memory_items(project_id)
            prefix = f"{project_id}::"
            items = []
            for row in rows:
                if row["tier"] not in tiers:
                    continue
                items.append(
                    MemoryItem.from_row(
                        {
                            **row,
                            "id": (
                                row["id"][len(prefix):]
                                if row["id"].startswith(prefix)
                                else row["id"]
                            ),
                        }
                    )
                )
        scored: List[Tuple[MemoryItem, float]] = []
        # 查询词只拆一次，供整个候选池复用
        q = (query or "").strip().lower()
        if not q:
            return []
        terms = query_terms(q)
        for item in items:
            if not item.is_visible_to(viewer):
                continue
            body = " ".join(
                [item.text, item.summary, " ".join(item.tags)]
            )
            score = score_terms(q, terms, body)
            if score > 0:
                scored.append((item, score))
        scored.sort(key=lambda pair: (-pair[1], -pair[0].scene_index))
        return scored[:limit]
