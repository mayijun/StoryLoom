"""扩展 manifest 校验与运行时解析测试（无需 API Key）。"""

import pytest

from storyloom.extensions.host import ExtensionRegistry
from storyloom.extensions.manifest import ManifestError, validate_manifest


def test_demo_manifests_resolve_and_travel_override(world):
    # 模板内嵌的扩展由 ExtensionRegistry 启动时自动加载，不再依赖 examples/ YAML
    registry = ExtensionRegistry()
    host = registry.for_instance("inst-1")
    resolved = host.resolve()
    assert any(item["id"] == "skill_xianxia" for item in resolved["skills"])
    assert any(item["id"] == "map_xianxia" for item in resolved["mods"])
    assert resolved["travel_overrides"]["演武场->杂役院"] == 8
    assert all(tool["read_only"] for tool in resolved["tools"])

    mapped = host.apply_map(world)
    assert "演武场" in mapped.locations
    assert mapped.locations["演武场"].exits["杂役院"] == 8
    # 旅行耗时仍由 mod 注入世界；是否移动由导演 Agent 裁决。
    assert host.travel_overrides()["演武场->杂役院"] == 8


def test_bad_manifest_rejected():
    with pytest.raises(ManifestError):
        validate_manifest(
            {
                "id": "bad_mod",
                "kind": "mod",
                "api_version": 1,
                "contributes": {
                    "rules": [
                        {"id": "evil", "handler": "os.system"}
                    ]
                },
            }
        )
    with pytest.raises(ManifestError):
        validate_manifest(
            {
                "id": "leaky_mod",
                "kind": "mod",
                "api_version": 1,
                "contributes": {
                    "tools": [
                        {"id": "leak", "read_only": False, "handler": "builtin.map.route"}
                    ]
                },
            }
        )
