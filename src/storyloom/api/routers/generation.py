"""场景生成API"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from storyloom.api.engine import engine
from storyloom.api.schemas import GenerateSceneRequest, GenerateSceneResponse
from storyloom.api.task_manager import TaskStatus, get_task_registry

router = APIRouter(prefix="/api/generate", tags=["generation"])


# ---------- 异步任务端点（前端轮询） ----------

class SubmitResponse(BaseModel):
    task_id: str


@router.post("/scene/submit", response_model=SubmitResponse)
async def submit_scene_generation(request: GenerateSceneRequest):
    """提交场景生成任务，立即返回 task_id，前端通过轮询 /tasks/{task_id} 取结果。

    相比同步 /scene，该接口不会被前端 HTTP 超时截断，
    且任务失败/完成后仍保留 10 分钟（由 TASK_TTL_SECONDS 控制）供前端收尾读取。
    """
    if request.project_id not in engine.projects:
        raise HTTPException(404, "Project not found")

    reg = get_task_registry()

    async def _run():
        # engine.generate_scene 内部已 run_in_executor 包 CrewAI 同步调用，
        # 在线程池里跑 asyncio 再 await 一次 run_in_executor 是安全的
        # （主循环在主线程，此处 loop.run_until_complete 绑定新循环）。
        reg.update_progress(task_id, progress=2, step="创建流程")
        result = await engine.generate_scene(request)
        return result.model_dump(mode="json")

    task_id = reg.submit(_run)
    return SubmitResponse(task_id=task_id)


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_generate_task(task_id: str):
    reg = get_task_registry()
    rec = reg.get(task_id)
    if rec is None:
        raise HTTPException(404, f"Task {task_id} not found (may have expired)")
    return rec


@router.delete("/tasks/{task_id}")
async def cancel_generate_task(task_id: str):
    """清理已完成/失败的任务记录；运行中的任务不会被中断（本实现不支持取消）"""
    reg = get_task_registry()
    rec = reg.pop(task_id)
    if rec is None:
        raise HTTPException(404, f"Task {task_id} not found")
    return {"deleted": task_id}


# ---------- 同步 & 流式端点（保留兼容） ----------

@router.post("/scene", response_model=GenerateSceneResponse)
async def generate_scene(request: GenerateSceneRequest):
    """同步生成场景（等待完成后返回）

    保留供 CLI / 测试脚本使用；前端优先用 /scene/submit + /tasks/{id} 轮询。
    """
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
