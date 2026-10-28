"""项目管理API"""

from fastapi import APIRouter, HTTPException
import uuid

from storyloom.api.schemas import ProjectCreate, ProjectView, ProjectListResponse
from storyloom.api.engine import engine

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/", response_model=ProjectListResponse)
async def list_projects():
    projects = []
    for pid, p in engine.projects.items():
        projects.append(ProjectView(
            project_id=pid,
            title=p.title,
            style=p.style,
            description="",
            scene_count=p.scene_count,
            character_count=len(p.characters),
            foreshadowing_count=len(p.foreshadowings),
        ))
    return ProjectListResponse(projects=projects, current_project_id=None)


@router.post("/", response_model=ProjectView)
async def create_project(data: ProjectCreate):
    pid = f"proj_{uuid.uuid4().hex[:8]}"
    project = engine.create_project(pid, data.title, data.style)
    return ProjectView(
        project_id=pid,
        title=project.title,
        style=project.style,
        description=data.description,
        scene_count=0,
        character_count=0,
        foreshadowing_count=0,
    )


@router.get("/{project_id}")
async def get_project(project_id: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return {
        "project_id": p.project_id,
        "title": p.title,
        "style": p.style,
        "characters": [c.model_dump() for c in p.characters],
        "locations": [l.model_dump() for l in p.locations],
        "foreshadowings": [f.model_dump(mode="json") for f in p.foreshadowings],
        "scene_count": p.scene_count,
    }
