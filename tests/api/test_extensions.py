"""扩展解析 API 测试（直接调用路由函数，不启动 HTTP 服务）。"""

import asyncio

from storyloom.api.schemas import ExtensionResolveRequest


def test_extensions_resolve_endpoint(apis):
    _, _, extensions = apis
    resolved = asyncio.run(
        extensions.resolve_extensions(
            ExtensionResolveRequest(instance_id="i1")
        )
    )
    assert resolved["instance_id"] == "i1"
    assert any(item["id"] == "map_xianxia" for item in resolved["mods"])
