"""运行时 API v1（M0 验收后的版本化入口）

复用 `/game/*`、`/extensions`、`/memory` 的处理函数，仅提供稳定前缀；
旧端点保留，后续逐步标记 deprecation。
"""

from fastapi import APIRouter

from storyloom.api.routers import extensions, game, memory

router = APIRouter(prefix="/runtime/v1", tags=["runtime-v1"])

router.add_api_route(
    "/{project_id}/turn", game.play_turn, methods=["POST"]
)
router.add_api_route(
    "/{project_id}/state", game.get_state, methods=["GET"]
)
router.add_api_route(
    "/{project_id}/saves", game.create_save, methods=["POST"]
)
router.add_api_route(
    "/{project_id}/saves", game.list_saves, methods=["GET"]
)
router.add_api_route(
    "/{project_id}/saves/{save_id}/load", game.load_save, methods=["POST"]
)
router.add_api_route(
    "/{project_id}/mode", game.switch_mode, methods=["POST"]
)
router.add_api_route(
    "/extensions/resolve", extensions.resolve_extensions, methods=["POST"]
)
router.add_api_route(
    "/projects/{project_id}/memory", memory.get_memory, methods=["GET"]
)
router.add_api_route(
    "/projects/{project_id}/memory", memory.patch_memory, methods=["PATCH"]
)
