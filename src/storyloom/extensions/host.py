"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

扩展宿主：按 instance_id 独立实例，不做类级缓存。

ExtensionHost 只负责读取 manifest 与提供确定性数据；
真正写状态仍然回到内核（GM / builtin handler）。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from storyloom.extensions.manifest import (
    ExtensionManifest,
    discover,
    load_manifest,
)
from storyloom.world.state import LocationState, WorldState


class ExtensionHost:
    """一个运行时实例的扩展视图"""

    def __init__(
        self,
        instance_id: str,
        manifests: Optional[List[ExtensionManifest]] = None,
        enabled: Optional[List[str]] = None,
    ):
        self.instance_id = instance_id
        self.manifests = list(manifests or [])
        self.enabled = set(enabled) if enabled is not None else None
        self._active = [
            m for m in self.manifests
            if m.enabled and (self.enabled is None or m.id in self.enabled)
        ]

    # ---------------- 查询 ----------------

    def of_kind(self, kind: str) -> List[ExtensionManifest]:
        return [m for m in self._active if m.kind == kind]

    @property
    def skills(self) -> List[ExtensionManifest]:
        return self.of_kind("skill")

    @property
    def mods(self) -> List[ExtensionManifest]:
        return self.of_kind("mod")

    def skill_prompt(self) -> str:
        """skill 只注入只读知识与文风"""
        blocks = []
        for manifest in self.skills:
            text = manifest.contributes.get("prompt") or manifest.description
            if text:
                blocks.append(f"【扩展·{manifest.name or manifest.id}】{text}")
        return "\n".join(blocks)

    def travel_overrides(self) -> Dict[str, int]:
        """mod 注入的旅行耗时覆盖，key = 起点->终点"""
        overrides: Dict[str, int] = {}
        for manifest in self.mods:
            map_data = manifest.contributes.get("map", {}) or {}
            routes = (
                map_data.get("routes")
                or manifest.contributes.get("routes", [])
                or []
            )
            for route in routes:
                origin = route.get("from")
                destination = route.get("to")
                minutes = route.get("minutes")
                if origin and destination and minutes is not None:
                    overrides[f"{origin}->{destination}"] = int(minutes)
        return overrides

    def rules(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for manifest in self.mods:
            for rule in manifest.contributes.get("rules", []) or []:
                result.append({**rule, "extension_id": manifest.id})
        return result

    def tools(self) -> List[Dict[str, Any]]:
        """提供给 LLM 的工具一律 read_only"""
        result: List[Dict[str, Any]] = []
        for manifest in self.mods:
            for tool in manifest.contributes.get("tools", []) or []:
                if tool.get("read_only"):
                    result.append({**tool, "extension_id": manifest.id})
        return result

    def assets(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for manifest in self.of_kind("asset"):
            for asset in manifest.contributes.get("assets", []) or []:
                result.append({**asset, "extension_id": manifest.id})
        return result

    def policies(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for manifest in self.of_kind("policy"):
            result.append(
                {
                    "id": manifest.id,
                    "config": manifest.contributes.get("policy", {}),
                }
            )
        return result

    def resolve(self) -> Dict[str, Any]:
        """给 API 的统一解析结果"""
        return {
            "instance_id": self.instance_id,
            "skills": [
                {"id": m.id, "name": m.name, "prompt": m.contributes.get("prompt", "")}
                for m in self.skills
            ],
            "mods": [
                {"id": m.id, "name": m.name, "rules": m.contributes.get("rules", [])}
                for m in self.mods
            ],
            "policies": self.policies(),
            "assets": self.assets(),
            "tools": self.tools(),
            "skill_prompt": self.skill_prompt(),
            "travel_overrides": self.travel_overrides(),
        }

    # ---------------- 世界注入 ----------------

    def apply_map(self, state: WorldState) -> WorldState:
        """把 mod 的地点与路线写入世界（只增不删）"""
        new = state.model_copy(deep=True)
        for manifest in self.mods:
            map_data = manifest.contributes.get("map", {}) or {}
            for location in map_data.get("locations", []) or []:
                name = location.get("name")
                if not name:
                    continue
                if name not in new.locations:
                    new.locations[name] = LocationState(
                        name=name,
                        description=location.get("description", ""),
                        tags=["mod", manifest.id],
                    )
            for route in map_data.get("routes", []) or []:
                origin = route.get("from")
                destination = route.get("to")
                minutes = int(route.get("minutes", 10))
                if origin in new.locations and destination:
                    new.locations[origin].exits[destination] = minutes
        return new


class ExtensionRegistry:
    """按 instance_id 创建独立宿主实例（不做类级缓存）"""

    def __init__(self, root: Optional[str] = None):
        self.root = root
        self._manifests: Optional[List[ExtensionManifest]] = None
        # 模板内嵌扩展：以 (template_id, manifest_id) 去重，避免重复 add
        self._template_keys: set[tuple[str, str]] = set()

    def manifests(self) -> List[ExtensionManifest]:
        if self._manifests is None:
            manifests = discover(self.root)
            self._manifests = manifests
            self._load_template_extensions()
        return self._manifests

    def _load_template_extensions(self) -> None:
        """把内置模板内嵌的扩展注册进来（不再依赖 examples/ 下的 YAML）。"""
        try:
            from storyloom.templates import TEMPLATES
        except Exception:
            return
        for template_id, template in TEMPLATES.items():
            for manifest in template.extension_manifests():
                key = (template_id, manifest.id)
                if key in self._template_keys:
                    continue
                self._template_keys.add(key)
                self._manifests.append(manifest)

    def add(self, manifest: ExtensionManifest) -> None:
        self.manifests().append(manifest)

    def for_instance(
        self, instance_id: str, enabled: Optional[List[str]] = None
    ) -> ExtensionHost:
        return ExtensionHost(
            instance_id=instance_id,
            manifests=list(self.manifests()),
            enabled=enabled,
        )

    def clear_cache(self) -> None:
        self._manifests = None
        self._template_keys = set()


def host_from_paths(
    instance_id: str,
    paths: List[str],
    enabled: Optional[List[str]] = None,
) -> ExtensionHost:
    """从显式 manifest 路径构建宿主（API / 测试使用）"""
    manifests = [load_manifest(Path(p)) for p in paths]
    return ExtensionHost(instance_id, manifests, enabled=enabled)


__all__ = [
    "ExtensionHost",
    "ExtensionRegistry",
    "host_from_paths",
]
