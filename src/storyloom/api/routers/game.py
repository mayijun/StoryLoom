"""游戏 / 扮演模式 API（M0，全部 async）"""

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from storyloom.api.engine import engine
from storyloom.api.schemas import (
    ModeSwitchRequest,
    SaveCreateRequest,
    TurnRequest,
)
from storyloom.flows.turn_flow import TurnBoot
from storyloom.runtime.intent import PlayerIntent
from storyloom.world.authority import FactOverride
from storyloom.world.state import WorldState

router = APIRouter(prefix="/game", tags=["game"])


def _ensure_project(project_id: str):
    if engine.get_project(project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目不存在: {project_id}",
        )


def _parse_intent(data: TurnRequest) -> PlayerIntent:
    """把请求体解析为 PlayerIntent；不合法时返回 422 而不是 500"""
    if data.intent is None:
        return PlayerIntent(kind="text", payload={"text": data.text})
    try:
        return PlayerIntent.model_validate(data.intent)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "intent 格式不合法",
                "expected": {
                    "kind": "text | choice | click | qte | skip | save | load | meta",
                    "payload": {"text": "自由文本", "action": "选项动作"},
                },
                "errors": exc.errors(
                    include_url=False, include_context=False, include_input=False
                ),
            },
        ) from exc


@router.post("/{project_id}/turn", deprecated=True)
async def play_turn(project_id: str, data: TurnRequest):
    """执行一个回合：游戏输入或导演指令"""
    _ensure_project(project_id)

    intent = _parse_intent(data)

    boot = TurnBoot(
        project_id=project_id,
        instance_id=data.instance_id,
        actor=data.actor,
        mode=data.mode,
        intent=intent,
        world_state=(
            WorldState.model_validate(data.world_state)
            if data.world_state
            else None
        ),
        max_turns=data.max_turns,
        max_retries=data.max_retries,
        max_cost=data.max_cost,
        max_duration_ms=data.max_duration_ms,
        enabled_extensions=data.enabled_extensions,
        memory_backend=data.memory_backend,
        idle_turns=data.idle_turns,
        switch_mode_to=data.switch_mode_to,
        overrides=[
            FactOverride.model_validate(item) for item in data.overrides
        ],
        goal=data.goal,
        provider_api_keys=dict(data.provider_api_keys),
    )
    result = await engine.play_turn(project_id, boot)
    return result.model_dump(mode="json")


@router.get("/{project_id}/opening")
async def get_opening(project_id: str, instance_id: str = "default"):
    """进入游戏模式时的开场（前情提要），不推进世界状态"""
    _ensure_project(project_id)
    return await engine.generate_opening(project_id, instance_id)


@router.get("/{project_id}/state", deprecated=True)
async def get_state(project_id: str, instance_id: str = "default"):
    """返回当前实例的运行时世界状态与记忆概览"""
    _ensure_project(project_id)
    state = engine.get_game_state(project_id, instance_id)
    memory = engine.memory_for(project_id)
    return {
        "state": state.model_dump(mode="json"),
        "view": state.view("玩家"),
        "memory": {
            "backend": memory.backend_name,
            "counts": memory.counts(),
        },
    }


@router.post("/{project_id}/saves", deprecated=True)
async def create_save(project_id: str, data: SaveCreateRequest):
    _ensure_project(project_id)
    record = engine.create_save(
        project_id,
        instance_id=data.instance_id,
        label=data.label,
        backlog=data.backlog,
    )
    return record.model_dump(mode="json", by_alias=True)


@router.get("/{project_id}/saves", deprecated=True)
async def list_saves(project_id: str):
    _ensure_project(project_id)
    return {
        "saves": [
            item.model_dump(mode="json", by_alias=True)
            for item in engine.list_saves(project_id)
        ]
    }


@router.post("/{project_id}/saves/{save_id}/load", deprecated=True)
async def load_save(
    project_id: str, save_id: str, instance_id: str = "default"
):
    _ensure_project(project_id)
    try:
        record = engine.load_save(project_id, save_id, instance_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return record.model_dump(mode="json", by_alias=True)


@router.post("/{project_id}/mode", deprecated=True)
async def switch_mode(project_id: str, data: ModeSwitchRequest):
    """模式切换：返回新状态与 checkpoint id"""
    _ensure_project(project_id)
    state, checkpoint_id = engine.switch_game_mode(
        project_id, data.mode, instance_id=data.instance_id
    )
    return {
        "state": state.model_dump(mode="json"),
        "checkpoint_id": checkpoint_id,
        "mode": state.mode,
    }
