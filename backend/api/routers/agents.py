"""Agent管理API"""

from fastapi import APIRouter
from typing import List

from api.schemas import AgentDefinition, AgentListResponse
from api.engine import engine

router = APIRouter(prefix="/api/agents", tags=["agents"])

# 内存中的Agent定义存储（生产环境用数据库）
agent_definitions: dict[str, AgentDefinition] = {}


@router.get("/", response_model=AgentListResponse)
async def list_agents():
    return AgentListResponse(
        agents=list(agent_definitions.values()),
        available_models=engine.get_available_models(),
    )


@router.post("/", response_model=AgentDefinition)
async def create_agent(agent: AgentDefinition):
    agent_definitions[agent.agent_id] = agent
    return agent


@router.put("/{agent_id}", response_model=AgentDefinition)
async def update_agent(agent_id: str, agent: AgentDefinition):
    agent.agent_id = agent_id
    agent_definitions[agent_id] = agent
    return agent


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    agent_definitions.pop(agent_id, None)
    return {"status": "ok"}


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
