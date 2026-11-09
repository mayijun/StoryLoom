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
    patch = data.model_dump(exclude_none=True)
    backend = patch.pop("backend", None)
    if backend is not None:
        patch.setdefault("retrieval", {})["backend"] = backend
    try:
        return engine.update_memory_config(project_id, patch)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
