"""场景历史API（已生成场景的查询 / 编辑 / 删除 / 章节归属）"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from storyloom.api.schemas import (
    GenerateSceneRequest,
    SceneAssignChapter,
    SceneUpdate,
    SceneView,
)
from storyloom.api.engine import engine
from storyloom.db import get_repository

router = APIRouter(prefix="/api/projects/{project_id}/scenes", tags=["scenes"])


@router.get("", response_model=list[SceneView])
async def list_scenes(
    project_id: str,
    chapter_id: Optional[str] = Query(
        None, description="按章节过滤；'null' 表示未归属章节的场景"
    ),
):
    if not engine.get_project(project_id):
        raise HTTPException(404, "Project not found")
    repo = get_repository()
    # 支持显式传 chapter_id=null 查询未归属场景
    if chapter_id == "null":
        chapter_id = None
    if chapter_id is not None:
        return repo.list_scenes_by_chapter(project_id, chapter_id)
    # 不传 chapter_id 时返回项目全部场景
    return repo.list_scenes(project_id)


@router.get("/{scene_id}", response_model=SceneView)
async def get_scene(project_id: str, scene_id: str):
    scene = get_repository().get_scene(scene_id)
    if scene is None or scene["project_id"] != project_id:
        raise HTTPException(404, "Scene not found")
    return scene


@router.put("/{scene_id}", response_model=SceneView)
async def update_scene(project_id: str, scene_id: str, data: SceneUpdate):
    repo = get_repository()
    scene = repo.get_scene(scene_id)
    if scene is None or scene["project_id"] != project_id:
        raise HTTPException(404, "Scene not found")
    fields = data.model_dump(exclude_unset=True)
    updated = repo.update_scene(scene_id, **fields)
    return updated


@router.patch("/{scene_id}/chapter", response_model=SceneView)
async def assign_scene_to_chapter(
    project_id: str, scene_id: str, data: SceneAssignChapter
):
    repo = get_repository()
    scene = repo.get_scene(scene_id)
    if scene is None or scene["project_id"] != project_id:
        raise HTTPException(404, "Scene not found")
    try:
        return repo.assign_scene_to_chapter(scene_id, data.chapter_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{scene_id}/regenerate")
async def regenerate_scene(project_id: str, scene_id: str):
    """用该场景已存的 brief + 在场角色重新生成正文，覆盖原场景。

    重跑不会递增项目的 scene_count，也不会推进伏笔沉睡计数。
    """
    repo = get_repository()
    scene = repo.get_scene(scene_id)
    if scene is None or scene["project_id"] != project_id:
        raise HTTPException(404, "Scene not found")

    request = GenerateSceneRequest(
        project_id=project_id,
        scene_brief=scene["brief"],
        present_character_names=list(scene.get("present_characters") or []),
        chapter_id=scene.get("chapter_id"),
    )
    return await engine.generate_scene(request, scene_id=scene_id)


@router.delete("/{scene_id}")
async def delete_scene(project_id: str, scene_id: str):
    repo = get_repository()
    scene = repo.get_scene(scene_id)
    if scene is None or scene["project_id"] != project_id:
        raise HTTPException(404, "Scene not found")
    repo.delete_scene(scene_id)
    return {"status": "ok"}
