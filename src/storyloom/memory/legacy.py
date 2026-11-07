"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

记忆基础版（保留兼容）：平铺 CoreMemory + SimpleRAGMemory。

作者模式仍在用这两个类；分层记忆 v2 见 core.LayeredMemory。
"""

import os
from typing import Dict, List

from pydantic import BaseModel, Field


class CoreMemory(BaseModel):
    """核心记忆：直接拼入每个 Agent 的 prompt"""

    recent_scene_summaries: List[str] = Field(default_factory=list)
    current_location: str = ""
    characters_present: List[str] = Field(default_factory=list)

    def as_prompt_block(self) -> str:
        summaries = "\n".join(
            f"  - {s}" for s in self.recent_scene_summaries[-3:]
        )
        return (
            f"【当前场景】地点: {self.current_location}；"
            f"在场角色: {', '.join(self.characters_present)}\n"
            f"【近期剧情摘要】\n{summaries or '  - （暂无）'}"
        )

    def add_scene_summary(self, prose: str, limit: int = 200):
        """把本场景摘要写回核心记忆（简化截断）"""
        self.recent_scene_summaries.append(prose[:limit] + "...")


class SimpleRAGMemory:
    """RAG 记忆层：用 ChromaDB 做向量检索，失败时退化为关键词检索"""

    def __init__(self, project_id: str, store_root: str = "./memory_store"):
        self.project_id = project_id
        self._fallback_docs: Dict[str, str] = {}
        self.collection = None

        if os.environ.get("DISABLE_CHROMADB") == "1":
            print("  ℹ️ DISABLE_CHROMADB=1，RAG 记忆退化为内存关键词检索")
            return

        try:
            import chromadb
        except ImportError:
            print("  ℹ️ 未安装 chromadb，RAG 记忆退化为内存关键词检索")
            return

        try:
            self.client = chromadb.PersistentClient(
                path=f"{store_root}/{project_id}"
            )
            self.collection = self.client.get_or_create_collection("lore")
        except Exception as exc:
            print(
                f"  ℹ️ ChromaDB 初始化失败: {type(exc).__name__}: {exc}"
            )
            self.collection = None
            self.client = None

    def add(self, doc_id: str, text: str, metadata: Dict):
        if self.collection is None:
            self._fallback_docs[doc_id] = text
            return

        try:
            self.collection.upsert(
                documents=[text], ids=[doc_id], metadatas=[metadata]
            )
        except Exception as exc:
            print(f"  ⚠️ RAG 写入失败 [{doc_id}]: {exc}")

    def query(self, query_text: str, n_results: int = 3) -> List[str]:
        if self.collection is None:
            return self._fallback_search(query_text, n_results)

        try:
            res = self.collection.query(
                query_texts=[query_text], n_results=n_results
            )
            return res["documents"][0] if res["documents"] else []
        except Exception:
            return []

    def _fallback_search(
        self, query_text: str, n_results: int
    ) -> List[str]:
        query_chars = set(query_text)
        scored = []
        for doc_id, text in self._fallback_docs.items():
            score = len(query_chars & set(text))
            scored.append((score, doc_id, text))
        scored.sort(reverse=True)
        return [text for score, _, text in scored[:n_results] if score > 0]
