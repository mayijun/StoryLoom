"""Agent 配置管理 API（数据库 CRUD）

数据存储在 agent_configs 表（默认 SQLite，可通过 STORYLOOM_DATABASE_URL
切换到 PostgreSQL / MySQL），与 CrewAI 的 Agent 配置字段一致。
"""

from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any

from storyloom.api.schemas import (
    AgentConfigInput,
    AgentConfigUpdate,
    AgentConfigView,
    AgentListResponse,
)
from storyloom.api.engine import engine
from storyloom.db import get_repository

router = APIRouter(prefix="/api/agents", tags=["agents"])

# 允许通过 API 显式置空的字段（其余字段忽略 None）
_NULLABLE_FIELDS = {"allow_delegation", "verbose", "max_iter"}


def _repo():
    repo = get_repository()
    # 保证首次请求前已建表并导入种子数据
    repo.ensure_seeded()
    return repo


@router.get("/", response_model=AgentListResponse)
async def list_agents():
    return AgentListResponse(
        agents=_repo().list_agents(),
        available_models=engine.get_available_models(),
    )


# 注意：静态路径必须声明在 /{key} 之前，否则会被动态路由吞掉
@router.get("/types")
async def get_agent_types():
    """返回所有可用的Agent类型及其说明"""
    return {
        "text_agents": [
            {
                "type": "protagonist",
                "name": "主角Agent",
                "description": "1角色=1实例，独立人格和记忆",
                "configurable": ["character_name", "model_provider", "temperature"],
                "status": "implemented",
            },
            {
                "type": "ensemble",
                "name": "群演Agent",
                "description": "1实例承载多个次要角色，压缩成本",
                "configurable": ["bound_character_ids", "model_provider", "temperature"],
                "status": "implemented",
            },
            {
                "type": "director",
                "name": "导演Agent",
                "description": "产出场景意图包，不写正文",
                "configurable": ["model_provider", "temperature"],
                "status": "implemented",
            },
            {
                "type": "surprise",
                "name": "意外Agent",
                "description": "提出合理但意外的事件提案",
                "configurable": ["model_provider", "temperature"],
                "status": "implemented",
            },
            {
                "type": "foreshadowing",
                "name": "伏笔Agent",
                "description": "管理伏笔生命周期",
                "configurable": ["model_provider", "temperature"],
                "status": "implemented",
            },
            {
                "type": "consistency",
                "name": "一致性检测Agent",
                "description": "校验人设/时间线/设定冲突",
                "configurable": ["model_provider", "temperature"],
                "status": "implemented",
            },
            {
                "type": "prose",
                "name": "润色Agent",
                "description": "把行动日志改写成文学正文",
                "configurable": ["model_provider", "temperature"],
                "status": "implemented",
            },
            {
                "type": "structuring",
                "name": "结构化Agent",
                "description": "正文→SceneIR中间表示",
                "configurable": ["model_provider", "temperature"],
                "status": "implemented",
            },
        ],
        "reserved_agents": [
            {"type": "visual", "name": "视觉Agent", "status": "reserved"},
            {"type": "audio", "name": "音频Agent", "status": "reserved"},
            {"type": "game_logic", "name": "游戏逻辑Agent", "status": "reserved"},
            {"type": "custom", "name": "自定义Agent", "status": "reserved"},
        ],
    }


@router.post(
    "/",
    response_model=AgentConfigView,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(agent: AgentConfigInput):
    repo = _repo()
    if repo.get_agent(agent.key) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent 已存在: {agent.key}",
        )
    payload: Dict[str, Any] = {
        key: value
        for key, value in agent.model_dump().items()
        if key != "key" and value is not None
    }
    return repo.upsert_agent(agent.key, **payload)


@router.get("/{key}", response_model=AgentConfigView)
async def get_agent(key: str):
    record = _repo().get_agent(key)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent 不存在: {key}",
        )
    return record


@router.put("/{key}", response_model=AgentConfigView)
async def update_agent(key: str, patch: AgentConfigUpdate):
    repo = _repo()
    existing = repo.get_agent(key)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent 不存在: {key}",
        )

    payload = patch.model_dump(exclude_unset=True)
    if payload.get("settings") is not None:
        # settings 为增量合并，避免覆盖其它自定义参数
        payload["settings"] = {**existing["settings"], **payload["settings"]}
    payload = {
        name: value
        for name, value in payload.items()
        if value is not None or name in _NULLABLE_FIELDS
    }
    if not payload:
        return existing
    return repo.upsert_agent(key, **payload)


@router.delete("/{key}")
async def delete_agent(key: str):
    if not _repo().delete_agent(key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent 不存在: {key}",
        )
    return {"status": "ok", "key": key}
