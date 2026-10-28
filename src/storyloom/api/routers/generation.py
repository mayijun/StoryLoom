"""场景生成API"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import json
import asyncio

from storyloom.api.schemas import GenerateSceneRequest, GenerateSceneResponse
from storyloom.api.engine import engine

router = APIRouter(prefix="/api/generate", tags=["generation"])


@router.post("/scene", response_model=GenerateSceneResponse)
async def generate_scene(request: GenerateSceneRequest):
    """同步生成场景（等待完成后返回）"""
    if request.project_id not in engine.projects:
        raise HTTPException(404, "Project not found")

    try:
        result = await engine.generate_scene(request)
        return result
    except Exception as e:
        raise HTTPException(500, f"Generation failed: {str(e)}")


@router.post("/scene/stream")
async def generate_scene_stream(request: GenerateSceneRequest):
    """
    SSE流式生成场景（实时推送步骤进度）
    前端用 EventSource 接收
    
    预留：未来可升级为 WebSocket 支持双向交互
    （用户中途干预Agent决策）
    """
    if request.project_id not in engine.projects:
        raise HTTPException(404, "Project not found")

    async def event_generator():
        # 发送开始事件
        yield f"data: {json.dumps({'type': 'start', 'message': '开始生成场景...'})}\n\n"

        steps = [
            ("propose_surprise", "意外Agent", "surprise"),
            ("propose_foreshadowing", "伏笔Agent", "foreshadowing"),
            ("plan_scene", "导演Agent", "director"),
            ("gather_rag", "RAG检索", "system"),
            ("actor_interaction", "角色互动", "actors"),
            ("consistency_check", "一致性检测", "consistency"),
            ("write_prose", "润色叙事", "prose"),
            ("update_memory", "更新记忆", "system"),
        ]

        for step_id, step_name, agent_type in steps:
            yield f"data: {json.dumps({'type': 'step_start', 'step': step_id, 'name': step_name, 'agent_type': agent_type})}\n\n"
            await asyncio.sleep(0.1)

        # 实际执行生成
        try:
            result = await engine.generate_scene(request)
            yield f"data: {json.dumps({'type': 'result', 'data': result.model_dump()})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        yield f"data: {json.dumps({'type': 'end'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
