"""扩展解析 API（M0）"""

from fastapi import APIRouter, HTTPException, status

from storyloom.api.engine import engine
from storyloom.api.schemas import ExtensionResolveRequest

router = APIRouter(prefix="/extensions", tags=["extensions"])


@router.post("/resolve", deprecated=True)
async def resolve_extensions(data: ExtensionResolveRequest):
    """解析某实例当前启用的扩展（skill / mod / policy / asset）"""
    try:
        return engine.resolve_extensions(
            data.instance_id, enabled=data.enabled
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
