"""项目管理 API

项目元数据落库（projects 表），与 agent_configs / task_configs 外键关联。
demo 内置项目禁止删除，其他项目删除时其 Agent / Task 配置级联清理。
另含：小说导出（Markdown / TXT）与项目指标（质量 / 耗时 / 模型用量）。
"""

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from urllib.parse import quote
import uuid

from storyloom.api.schemas import (
    ProjectCreate,
    ProjectMetrics,
    ProjectView,
    ProjectListResponse,
    SceneMetric,
)
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


@router.get("/{project_id}/export")
async def export_novel(
    project_id: str,
    format: str = Query("md", pattern="^(md|txt)$"),
):
    """导出整本小说：按章节（position 排序）组织已落库场景正文，
    未归属章节的场景附在末尾。md 带 Markdown 标记，txt 为纯文本。"""
    repo = get_repository()
    meta = repo.get_project(project_id)
    if meta is None:
        raise HTTPException(404, "Project not found")

    chapters = repo.list_chapters(project_id)
    all_scenes = repo.list_scenes(project_id)
    assigned = {s["scene_id"] for c in chapters
                for s in repo.list_scenes_by_chapter(project_id, c["chapter_id"])}
    loose_scenes = [s for s in all_scenes if s["scene_id"] not in assigned]

    is_md = format == "md"
    lines: list[str] = []
    lines.append(f"# {meta['title']}" if is_md else meta["title"])
    if meta.get("style"):
        lines.append(f"> 文风：{meta['style']}" if is_md else f"文风：{meta['style']}")
    lines.append("")

    def _emit_scene(scene: dict) -> None:
        heading = f"场景 {scene['scene_id']}"
        lines.append(f"### {heading}" if is_md else f"【{heading}】")
        lines.append("")
        body = scene.get("prose") or f"（未生成正文）brief：{scene['brief']}"
        lines.append(body)
        lines.append("")

    for idx, chapter in enumerate(chapters, 1):
        title = f"第{idx}章 {chapter['title']}"
        lines.append(f"## {title}" if is_md else f"\n===== {title} =====")
        if chapter.get("outline"):
            lines.append(f"> {chapter['outline']}" if is_md else chapter["outline"])
        lines.append("")
        for scene in repo.list_scenes_by_chapter(project_id, chapter["chapter_id"]):
            _emit_scene(scene)

    if loose_scenes:
        lines.append("## 未归属场景" if is_md else "\n===== 未归属场景 =====")
        lines.append("")
        for scene in loose_scenes:
            _emit_scene(scene)

    text = "\n".join(lines)
    ext = "md" if is_md else "txt"
    filename = f"{meta['title']}.{ext}"
    # Content-Disposition 同时给 ASCII 兜底名与 UTF-8 名（中文标题）
    disposition = (
        f"attachment; filename=novel.{ext}; "
        f"filename*=UTF-8''{quote(filename)}"
    )
    return PlainTextResponse(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


@router.get("/{project_id}/metrics", response_model=ProjectMetrics)
async def project_metrics(project_id: str):
    """成本与质量指标：质量分 / 耗时 / 模型与 Agent 调用量（按场景聚合）。"""
    repo = get_repository()
    if not repo.project_exists(project_id):
        raise HTTPException(404, "Project not found")
    scenes = repo.list_scenes(project_id)

    quality = [s["quality_score"] for s in scenes
               if s.get("quality_score") is not None]
    durations = [s["duration_ms"] for s in scenes
                 if s.get("duration_ms") is not None]
    model_calls: dict[str, int] = {}
    agent_calls: dict[str, int] = {}
    for s in scenes:
        for agent_key, model_key in (s.get("model_usage") or {}).items():
            model_calls[model_key] = model_calls.get(model_key, 0) + 1
            agent_calls[agent_key] = agent_calls.get(agent_key, 0) + 1

    return ProjectMetrics(
        project_id=project_id,
        scene_count=len(scenes),
        avg_quality_score=(
            round(sum(quality) / len(quality), 3) if quality else None
        ),
        total_duration_ms=sum(durations),
        avg_duration_ms=(
            round(sum(durations) / len(durations), 1) if durations else None
        ),
        model_calls=dict(sorted(model_calls.items(), key=lambda kv: -kv[1])),
        agent_calls=dict(sorted(agent_calls.items(), key=lambda kv: -kv[1])),
        scenes=[
            SceneMetric(
                scene_id=s["scene_id"],
                chapter_id=s.get("chapter_id"),
                quality_score=s.get("quality_score"),
                duration_ms=s.get("duration_ms"),
                created_at=s.get("created_at"),
            )
            for s in scenes
        ],
    )


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
