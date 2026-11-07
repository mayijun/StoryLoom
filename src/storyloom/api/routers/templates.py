"""试用模板 API：列出可用模板，一键应用为新项目。"""

from fastapi import APIRouter, HTTPException, status

from storyloom.api.engine import engine
from storyloom.api.schemas import (
    ProjectView,
    TemplateApplyRequest,
    TemplateListResponse,
    TemplateView,
)

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("/", response_model=TemplateListResponse)
async def list_templates():
    templates = [TemplateView(**t) for t in engine.list_templates()]
    return TemplateListResponse(templates=templates)


@router.post("/{template_id}/apply", response_model=ProjectView)
async def apply_template(template_id: str, data: TemplateApplyRequest):
    """应用模板，生成一个可删除的普通项目。"""
    try:
        meta = engine.apply_template(template_id, title=data.title)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return ProjectView(
        project_id=meta["project_id"],
        title=meta["title"],
        style=meta["style"],
        description=meta["description"],
        scene_count=meta.get("scene_count", 0),
        character_count=meta.get("character_count", 0),
        foreshadowing_count=meta.get("foreshadowing_count", 0),
    )
