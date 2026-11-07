"""分层记忆 API（M0）：查看与切换检索后端"""

from fastapi import APIRouter, HTTPException, status

from storyloom.api.engine import engine
from storyloom.api.schemas import MemoryPatchRequest

router = APIRouter(prefix="/api/projects", tags=["memory"])


@router.get("/{project_id}/memory")
async def get_memory(project_id: str):
    if engine.get_project(project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目不存在: {project_id}",
        )
    return engine.memory_overview(project_id)


@router.patch("/{project_id}/memory")
async def patch_memory(project_id: str, data: MemoryPatchRequest):
    if engine.get_project(project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目不存在: {project_id}",
        )
    try:
        return engine.set_memory_backend(project_id, data.backend)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
