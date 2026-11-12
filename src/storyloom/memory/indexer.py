"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

历史回填：把旧项目的场景与资产补进检索库。

作品数据是事实来源，记忆索引可随时删除重建。
"""

from typing import Any, Iterable, List, Optional

from storyloom.memory.core import LayeredMemory
from storyloom.memory.scoring import score_importance


class MemoryIndexer:
    """把已有 scenes / characters / locations 回填为 archive 记忆"""

    def __init__(self, memory: LayeredMemory):
        self.memory = memory

    def backfill(
        self,
        scenes: Iterable[Any],
        characters: Optional[Iterable[Any]] = None,
        locations: Optional[Iterable[Any]] = None,
        force: bool = False,
    ) -> int:
        """幂等回填；已有场景记忆时只跳过场景，资产仍保持最新。

        传入的资产集合即事实来源：已删除 / 改名的角色、地点会被清理。
        角色秘密独立存储在记忆条目中，只有在角色本身被删除时才清理。
        某一类资产传 None 表示不参与本次回填，因而也不清理该类旧条目。
        """
        count = 0
        backfill_scenes = force or not self.memory.has_scene_memory()
        scene_source = scenes if backfill_scenes else ()

        for index, scene in enumerate(scene_source):
            scene_id = _get(scene, "scene_id") or f"scene_{index}"
            brief = _get(scene, "brief") or ""
            prose = _get(scene, "prose") or ""
            text = f"{brief}\n{prose}".strip()
            if not text:
                continue
            present = [
                name for name in (_get(scene, "present_characters") or [])
                if name
            ]
            before = len(self.memory.items)
            self.memory.add_archive_item(
                item_id=f"scene:{scene_id}",
                text=text,
                scene_index=index,
                importance=score_importance(text, brief=brief),
                tags=["scene", "backfill"],
                known_by=present or None,
                source="backfill",
            )
            if len(self.memory.items) > before:
                count += 1

        keep_char: Optional[set[str]] = None
        if characters is not None:
            keep_char = set()
            for char in characters:
                name = _get(char, "name") or ""
                if not name:
                    continue
                persona = _get(char, "persona") or ""
                motivation = _get(char, "motivation") or ""
                self.memory.add_archive_item(
                    item_id=f"char:{name}",
                    text=f"{name}：{persona}。动机：{motivation}",
                    tags=["character", "asset"],
                    source="asset",
                )
                keep_char.add(f"char:{name}")
                count += 1

        keep_loc: Optional[set[str]] = None
        if locations is not None:
            keep_loc = set()
            for loc in locations:
                name = _get(loc, "name") or ""
                description = _get(loc, "description") or ""
                if not name:
                    continue
                self.memory.add_archive_item(
                    item_id=f"loc:{name}",
                    text=f"{name}：{description}",
                    tags=["location", "asset"],
                    source="asset",
                )
                keep_loc.add(f"loc:{name}")
                count += 1

        self._prune_stale_assets(keep_char, keep_loc)
        return count

    def _prune_stale_assets(
        self,
        keep_char: Optional[set[str]],
        keep_loc: Optional[set[str]],
    ) -> None:
        """删除已不在数据库资产中的 char:/secret:/loc: 条目。

        只处理 source=asset 的归档项，避免误删降级记忆或回填场景。
        secret 条目独立于角色资产存储，仅在角色本身被删除时清理。
        """
        for item in list(self.memory.items.values()):
            if item.tier != "archive" or item.source != "asset":
                continue
            if item.id.startswith("char:"):
                if keep_char is not None and item.id not in keep_char:
                    self.memory._drop(item.id)
            elif item.id.startswith("secret:"):
                name = item.id[len("secret:"):]
                if (
                    keep_char is not None
                    and f"char:{name}" not in keep_char
                ):
                    self.memory._drop(item.id)
            elif item.id.startswith("loc:"):
                if keep_loc is not None and item.id not in keep_loc:
                    self.memory._drop(item.id)


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


__all__ = ["MemoryIndexer"]
