"""资产管理API"""

from fastapi import APIRouter, HTTPException

from api.schemas import CharacterCreate, LocationCreate
from api.engine import engine
from assets.models import CharacterAsset, LocationAsset, Foreshadowing

router = APIRouter(prefix="/api/projects/{project_id}/assets", tags=["assets"])


@router.post("/characters")
async def add_character(project_id: str, data: CharacterCreate):
    if project_id not in engine.projects:
        raise HTTPException(404, "Project not found")
    char = CharacterAsset(**data.model_dump(exclude={"portrait_url", "voice_id"}))
    engine.add_character(project_id, char)
    return {"status": "ok", "character": char.model_dump()}


@router.get("/characters")
async def list_characters(project_id: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    return [c.model_dump() for c in p.characters]


@router.delete("/characters/{name}")
async def delete_character(project_id: str, name: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    p.characters = [c for c in p.characters if c.name != name]
    return {"status": "ok"}


@router.post("/locations")
async def add_location(project_id: str, data: LocationCreate):
    if project_id not in engine.projects:
        raise HTTPException(404)
    loc = LocationAsset(name=data.name, description=data.description)
    engine.add_location(project_id, loc)
    return {"status": "ok", "location": loc.model_dump()}


@router.get("/locations")
async def list_locations(project_id: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    return [l.model_dump() for l in p.locations]


@router.post("/foreshadowings")
async def add_foreshadowing(project_id: str, data: dict):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    fs = Foreshadowing(**data)
    p.foreshadowings.append(fs)
    return {"status": "ok", "foreshadowing": fs.model_dump(mode="json")}


@router.get("/foreshadowings")
async def list_foreshadowings(project_id: str):
    p = engine.get_project(project_id)
    if not p:
        raise HTTPException(404)
    return [f.model_dump(mode="json") for f in p.foreshadowings]
