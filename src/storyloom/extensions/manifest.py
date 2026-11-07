"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

统一扩展 manifest：skill / mod / policy / asset。

纪律：
- v1 只支持 YAML + 白名单 builtin handler；
- mod 的状态变更必须走 builtin handler；
- 暴露给 LLM 的工具一律 read_only；
- Python 包 + capabilities 只预留接口（v2）。
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

# v1 允许 mod 调用的确定性 handler 白名单
BUILTIN_HANDLERS = {
    "builtin.map.move",
    "builtin.map.route",
    "builtin.time.advance",
    "builtin.flag.set",
    "builtin.relationship.adjust",
}

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ManifestError(ValueError):
    """manifest 校验失败"""


class ExtensionManifest(BaseModel):
    id: str
    kind: Literal["skill", "mod", "policy", "asset"]
    api_version: int = 1
    name: str = ""
    description: str = ""
    enabled: bool = True
    requires: Dict[str, Any] = Field(default_factory=dict)
    contributes: Dict[str, Any] = Field(default_factory=dict)
    path: Optional[str] = None


def validate_manifest(data: Dict[str, Any]) -> ExtensionManifest:
    """校验并返回 manifest；任何越权都在这里拦下"""
    try:
        manifest = ExtensionManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestError(f"manifest 结构非法: {exc}") from exc

    if not _ID_PATTERN.match(manifest.id):
        raise ManifestError(
            f"扩展 id 非法（需小写字母开头）: {manifest.id}"
        )
    if manifest.api_version != 1:
        raise ManifestError(
            f"不支持的 api_version: {manifest.api_version}"
        )

    if manifest.kind == "mod":
        rules = manifest.contributes.get("rules", []) or []
        for rule in rules:
            handler = str(rule.get("handler", ""))
            if handler not in BUILTIN_HANDLERS:
                raise ManifestError(
                    f"mod 规则使用了未授权 handler: {handler}"
                )
        tools = manifest.contributes.get("tools", []) or []
        for tool in tools:
            if not tool.get("read_only", False):
                raise ManifestError(
                    f"LLM 工具必须 read_only: {tool.get('id')}"
                )
            handler = str(tool.get("handler", ""))
            if handler and handler not in BUILTIN_HANDLERS:
                raise ManifestError(
                    f"工具使用了未授权 handler: {handler}"
                )
    return manifest


def load_manifest(path: Path) -> ExtensionManifest:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest 必须是 YAML 对象: {path}")
    raw.setdefault("id", path.stem)
    raw.setdefault("kind", "mod")
    raw["path"] = str(path)
    return validate_manifest(raw)


def discover(root: Optional[str] = None) -> List[ExtensionManifest]:
    """扫描目录下所有 *.yaml / *.yml manifest"""
    if root is None:
        root_path = Path(__file__).resolve().parents[1] / "examples"
    else:
        root_path = Path(root)
    if not root_path.exists():
        return []
    manifests: List[ExtensionManifest] = []
    for path in sorted(root_path.rglob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(raw, dict) or "kind" not in raw:
            continue
        manifests.append(load_manifest(path))
    for path in sorted(root_path.rglob("*.yml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(raw, dict) or "kind" not in raw:
            continue
        manifests.append(load_manifest(path))
    return manifests


__all__ = [
    "BUILTIN_HANDLERS",
    "ExtensionManifest",
    "ManifestError",
    "discover",
    "load_manifest",
    "validate_manifest",
]
