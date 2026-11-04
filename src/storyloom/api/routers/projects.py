"""项目管理 API

项目元数据落库（projects 表），与 agent_configs / task_configs 外键关联。
demo 内置项目禁止删除，其他项目删除时其 Agent / Task 配置级联清理。
"""

from fastapi import APIRouter, HTTPException, status
import uuid

from storyloom.api.schemas import ProjectCreate, ProjectView, ProjectListResponse
from storyloom.api.engine import engine
from storyloom.db import DEFAULT_PROJECT_ID, get_repository

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _view_from_meta(meta: dict) -> ProjectView:
    return ProjectView(
        project_id=meta["project_id"],
        title=meta["title"],
        style=meta["style"],
        description=meta["description"],
        scene_count=meta["scene_count"],
        character_count=meta["character_count"],
        foreshadowing_count=meta["foreshadowing_count"],
    )


@router.get("/", response_model=ProjectListResponse)
async def list_projects():
    repo = get_repository()
    projects = [_view_from_meta(meta) for meta in repo.list_projects()]
    return ProjectListResponse(
        projects=projects,
        current_project_id=engine.list_projects()[0]["project_id"]
        if projects
        else None,
    )


@router.post("/", response_model=ProjectView)
async def create_project(data: ProjectCreate):
    pid = f"proj_{uuid.uuid4().hex[:8]}"
    try:
        engine.create_project(pid, data.title, data.style, data.description)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    meta = get_repository().get_project(pid)
    return _view_from_meta(meta)


@router.get("/{project_id}")
async def get_project(project_id: str):
    repo = get_repository()
    meta = repo.get_project(project_id)
    if meta is None:
        raise HTTPException(404, "Project not found")
    project = engine.get_project(project_id)
    return {
        **meta,
        "characters": [c.model_dump() for c in project.characters],
        "locations": [l.model_dump() for l in project.locations],
        "foreshadowings": [
            f.model_dump(mode="json") for f in project.foreshadowings
        ],
    }


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """
    删除项目。demo 内置项目禁止删除；
    其余项目删除时其 Agent / Task 配置级联清理（外键 ON DELETE CASCADE）。
    """
    repo = get_repository()
    if project_id == DEFAULT_PROJECT_ID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="demo 内置项目禁止删除",
        )
    if not repo.project_exists(project_id):
        raise HTTPException(404, "Project not found")
    repo.delete_project(project_id)
    # 同时清理内存缓存
    engine._project_runtime.pop(project_id, None)
    engine.memories.pop(project_id, None)
    engine.rags.pop(project_id, None)
    return {"status": "ok", "project_id": project_id}
