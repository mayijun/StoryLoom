"""资产管理API（角色 / 场景 / 伏笔）。

数据落库（characters / locations / foreshadowings 表），
通过 engine 的方法同步写入 DB 与运行时 NovelProject 对象。
"""

from fastapi import APIRouter, HTTPException

from storyloom.api.schemas import (
    CharacterCreate,
    ForeshadowTransition,
    ForeshadowingView,
    LocationCreate,
)
from storyloom.api.engine import engine
from storyloom.memory.models import CharacterAsset, LocationAsset, Foreshadowing

router = APIRouter(prefix="/api/projects/{project_id}/assets", tags=["assets"])


# ---------------- 角色 ----------------

@router.post("/characters")
async def add_character(project_id: str, data: CharacterCreate):
    if project_id not in engine.projects:
        raise HTTPException(404, "Project not found")
    char = CharacterAsset(
        **data.model_dump(
            exclude={"portrait_url", "voice_id", "secrets"}
        )
    )
    engine.add_character(project_id, char, secrets=data.secrets)
    return {
        "status": "ok",
        "character": {**char.model_dump(), "secrets": data.secrets},
    }


@router.get("/characters")
async def list_characters(project_id: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    return engine.character_payloads(project_id)


@router.delete("/characters/{name}")
async def delete_character(project_id: str, name: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    engine.delete_character(project_id, name)
    return {"status": "ok"}


# ---------------- 场景 / 地点 ----------------

@router.post("/locations")
async def add_location(project_id: str, data: LocationCreate):
    if project_id not in engine.projects:
        raise HTTPException(404, "Project not found")
    loc = LocationAsset(name=data.name, description=data.description)
    engine.add_location(project_id, loc)
    return {"status": "ok", "location": loc.model_dump()}


@router.get("/locations")
async def list_locations(project_id: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    return [l.model_dump() for l in p.locations]


@router.delete("/locations/{name}")
async def delete_location(project_id: str, name: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    from storyloom.db import get_repository
    get_repository().delete_location_asset(name, project_id)
    p.locations = [l for l in p.locations if l.name != name]
    return {"status": "ok"}


# ---------------- 伏笔 ----------------

@router.post("/foreshadowings")
async def add_foreshadowing(project_id: str, data: dict):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    fs = Foreshadowing(**data)
    conflicts = await engine.check_foreshadow_conflicts(project_id, fs)
    if any(c.get("severity") == "major" for c in conflicts):
        raise HTTPException(
            status_code=409,
            detail={"conflicts": conflicts},
        )
    engine.add_foreshadowing(project_id, fs)
    return {
        "status": "ok",
        "foreshadowing": fs.model_dump(mode="json"),
        "conflicts": [
            c for c in conflicts if c.get("severity") != "major"
        ],
    }


@router.get("/foreshadowings")
async def list_foreshadowings(project_id: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    return [f.model_dump(mode="json") for f in p.foreshadowings]


@router.post(
    "/foreshadowings/{foreshadow_id}/transition",
    response_model=ForeshadowingView,
)
async def transition_foreshadowing(
    project_id: str, foreshadow_id: str, data: ForeshadowTransition
):
    """伏笔状态显式流转：reinforce / activate / resolve / subvert /
    abandon / replant。非法流转返回 409。"""
    if not engine.get_project(project_id):
        raise HTTPException(404, "Project not found")
    try:
        fs = engine.transition_foreshadowing(
            project_id, foreshadow_id, data.action
        )
    except KeyError:
        raise HTTPException(404, f"伏笔不存在: {foreshadow_id}")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return ForeshadowingView(
        foreshadow_id=fs.foreshadow_id,
        description=fs.description,
        status=fs.status.value,
        planted_in_scene=fs.planted_in_scene,
        target_revelation=fs.target_revelation,
        reinforcement_count=fs.reinforcement_count,
        scenes_since_last_mention=fs.scenes_since_last_mention,
        max_dormant_scenes=fs.max_dormant_scenes,
        linked_characters=fs.linked_characters,
        visibility=fs.visibility,
        known_by=fs.known_by,
    )


@router.delete("/foreshadowings/{foreshadow_id}")
async def delete_foreshadowing(project_id: str, foreshadow_id: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    engine.delete_foreshadowing(project_id, foreshadow_id)
    return {"status": "ok"}
