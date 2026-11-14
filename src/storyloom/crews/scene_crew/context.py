"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

统一管理注入到各 Agent prompt 的上下文维度。

设计原则：
  - 所有 Agent 共用同一份场景级上下文 + 同一个 LayeredMemory 实例；
  - Agent 之间的区别只在 viewer（记忆可见性）以及各维度的开关；
  - 每个维度方法在内容为空时返回 ""，build() 自动跳过空块，
    不会出现「【记忆】\n（无）」之类的噪音。
"""

from __future__ import annotations

from typing import Any, List, Optional

from storyloom.memory import LayeredMemory
from storyloom.memory.models import NovelProject


class PromptContextAssembler:
    """按维度拼装 Agent prompt 的上下文块。

    用法::

        assembler = PromptContextAssembler(
            memory=self.memory,
            project=project,
            scene_brief=scene_brief,
            present_chars=present_chars,
            foreshadow_table=self._foreshadow_summary(project),
            extensions=self.extensions,
        )
        # 导演：场景 + 角色一览 + 伏笔 + 记忆 + RAG
        ctx = assembler.build("director", query=scene_brief,
                              include_scene=True, include_cast=True,
                              include_foreshadow=True)
        # 角色：记忆 + RAG + 导演意图
        ctx = assembler.build(char.name, query=scene_brief,
                              include_intent=True)
        # 导演意图产出后再回写
        assembler.director_intent = json.dumps(director_json["director_intent"])
    """

    def __init__(
        self,
        *,
        memory: Optional[LayeredMemory],
        project: NovelProject,
        scene_brief: str,
        present_chars: List[str],
        foreshadow_table: str = "",
        extensions: Optional[Any] = None,
    ) -> None:
        self.memory = memory
        self.project = project
        self.scene_brief = scene_brief
        self.present_chars = list(present_chars)
        self.foreshadow_table = foreshadow_table
        self.extensions = extensions
        # 导演意图在 director kickoff 之后才知道，由调用方回写
        self.director_intent: str = ""

    # ------------------------------------------------------------------
    # 记忆维度（viewer 相关）
    # ------------------------------------------------------------------

    def memory_block(self, viewer: str) -> str:
        """L0～L3 分层记忆，按 visible_to(viewer) 过滤。"""
        if self.memory is None:
            return ""
        try:
            block = self.memory.prompt_block(viewer=viewer)
        except Exception:  # noqa: BLE001 - 记忆不可用时静默降级
            return ""
        if not block.strip():
            return ""
        return f"【记忆】\n{block}"

    def rag_context(self, viewer: str, query: str = "", k: int = 3) -> str:
        """archive 层检索 top-k，检索池先按 viewer 过滤。"""
        if self.memory is None or not query:
            return ""
        try:
            block = self.memory.retrieval_block(query, k=k, viewer=viewer)
        except Exception:  # noqa: BLE001
            return ""
        if not block.strip():
            return ""
        return f"【相关回忆检索】\n{block}"

    # ------------------------------------------------------------------
    # 场景级共享维度（所有 Agent 相同）
    # ------------------------------------------------------------------

    def scene_block(self) -> str:
        """场景描述 + 在场角色列表。"""
        parts = [
            f"【scene_brief/玩家行动】: {self.scene_brief or '（未提供）'}",
            f"【已出场角色】: {', '.join(self.present_chars) or '（无）'}",
        ]
        return "\n".join(parts)

    def cast_block(self) -> str:
        """全部角色一览 + 地点一览。"""
        parts: List[str] = []
        if self.project.characters:
            char_brief = "\n".join(
                f"- {c.name}（{c.importance_tier}）：{c.persona[:60]}"
                for c in self.project.characters[:6]
            )
            parts.append(f"【全部角色一览】:\n{char_brief}")
        if self.project.locations:
            loc_brief = ", ".join(l.name for l in self.project.locations[:6])
            parts.append(f"【地点一览】: {loc_brief}")
        return "\n".join(parts)

    def foreshadow_block(self) -> str:
        """伏笔简要状态表（DirectorAgent 看简要，详情用 tool 查）。"""
        if not self.foreshadow_table.strip():
            return ""
        return f"【伏笔简要状态表】:\n{self.foreshadow_table}"

    def intent_block(self) -> str:
        """导演意图（director kickoff 之后由调用方回写）。"""
        if not self.director_intent.strip():
            return ""
        return f"【导演意图】\n{self.director_intent}"

    def extension_block(self) -> str:
        """扩展设定与规则。"""
        if self.extensions is None:
            return ""
        parts: List[str] = []
        try:
            skill_text = self.extensions.skill_prompt()
            if skill_text:
                parts.append(f"【扩展设定】\n{skill_text}")
            rules = self.extensions.rules()
            if rules:
                import json

                parts.append(
                    "【扩展规则】\n"
                    + json.dumps(rules, ensure_ascii=False, indent=2)
                )
        except Exception:  # noqa: BLE001 - 扩展不可用不阻断
            return ""
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 一键拼装
    # ------------------------------------------------------------------

    def build(
        self,
        viewer: str,
        *,
        query: str = "",
        k: int = 3,
        include_scene: bool = False,
        include_cast: bool = False,
        include_foreshadow: bool = False,
        include_memory: bool = True,
        include_rag: bool = True,
        include_intent: bool = False,
        include_extension: bool = False,
    ) -> str:
        """按维度开关拼装上下文块，空块自动跳过。"""
        parts: List[str] = []
        if include_scene:
            parts.append(self.scene_block())
        if include_cast:
            parts.append(self.cast_block())
        if include_foreshadow:
            parts.append(self.foreshadow_block())
        if include_memory:
            parts.append(self.memory_block(viewer))
        if include_rag:
            parts.append(self.rag_context(viewer, query, k))
        if include_intent:
            parts.append(self.intent_block())
        if include_extension:
            parts.append(self.extension_block())
        return "\n\n".join(p for p in parts if p)
