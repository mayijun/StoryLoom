"""章节结构 API"""

import uuid

from fastapi import APIRouter, HTTPException

from storyloom.api.schemas import ChapterCreate, ChapterUpdate, ChapterView
from storyloom.api.engine import engine
from storyloom.db import get_repository

router = APIRouter(prefix="/api/projects/{project_id}/chapters", tags=["chapters"])


def _gen_chapter_id() -> str:
    return f"ch_{uuid.uuid4().hex[:8]}"


@router.get("", response_model=list[ChapterView])
async def list_chapters(project_id: str):
    if not engine.get_project(project_id):
        raise HTTPException(404, "Project not found")
    return get_repository().list_chapters(project_id)


@router.get("/{chapter_id}", response_model=ChapterView)
async def get_chapter(project_id: str, chapter_id: str):
    repo = get_repository()
    ch = repo.get_chapter(chapter_id)
    if ch is None or ch["project_id"] != project_id:
        raise HTTPException(404, "Chapter not found")
    return ch


@router.post("", response_model=ChapterView)
async def create_chapter(project_id: str, data: ChapterCreate):
    if not engine.get_project(project_id):
        raise HTTPException(404, "Project not found")
    chapter_id = _gen_chapter_id()
    return get_repository().create_chapter(
        chapter_id=chapter_id,
        project_id=project_id,
        title=data.title,
        outline=data.outline,
        position=data.position,
        status=data.status,
    )


@router.put("/{chapter_id}", response_model=ChapterView)
async def update_chapter(project_id: str, chapter_id: str, data: ChapterUpdate):
    repo = get_repository()
    ch = repo.get_chapter(chapter_id)
    if ch is None or ch["project_id"] != project_id:
        raise HTTPException(404, "Chapter not found")
    fields = data.model_dump(exclude_unset=True)
    updated = repo.update_chapter(chapter_id, **fields)
    return updated


@router.delete("/{chapter_id}")
async def delete_chapter(project_id: str, chapter_id: str):
    repo = get_repository()
    ch = repo.get_chapter(chapter_id)
    if ch is None or ch["project_id"] != project_id:
        raise HTTPException(404, "Chapter not found")
    repo.delete_chapter(chapter_id)
    return {"status": "ok"}
