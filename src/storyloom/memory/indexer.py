"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

历史回填：把旧项目的场景与资产补进检索库。

作品数据是事实来源，记忆索引可随时删除重建。
"""

from typing import Any, Iterable, List

from storyloom.memory.core import LayeredMemory
from storyloom.memory.scoring import score_importance


class MemoryIndexer:
    """把已有 scenes / characters / locations 回填为 archive 记忆"""

    def __init__(self, memory: LayeredMemory):
        self.memory = memory

    def backfill(
        self,
        scenes: Iterable[Any],
        characters: Iterable[Any] = (),
        locations: Iterable[Any] = (),
        force: bool = False,
    ) -> int:
        """幂等回填；已有场景记忆时默认跳过"""
        if self.memory.has_scene_memory() and not force:
            return 0

        count = 0

        for index, scene in enumerate(scenes):
            scene_id = _get(scene, "scene_id") or f"scene_{index}"
            brief = _get(scene, "brief") or ""
            prose = _get(scene, "prose") or ""
            text = f"{brief}\n{prose}".strip()
            if not text:
                continue
            before = len(self.memory.items)
            self.memory.add_archive_item(
                item_id=f"scene:{scene_id}",
                text=text,
                scene_index=index,
                importance=score_importance(text, brief=brief),
                tags=["scene", "backfill"],
                source="backfill",
            )
            if len(self.memory.items) > before:
                count += 1

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
            count += 1
            secrets = _get(char, "secrets") or ""
            if secrets:
                self.memory.add_archive_item(
                    item_id=f"secret:{name}",
                    text=f"{name}的秘密：{secrets}",
                    tags=["secret", "asset"],
                    visibility=f"private:{name}",
                    source="asset",
                )
                count += 1

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
            count += 1

        return count


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


__all__ = ["MemoryIndexer"]
