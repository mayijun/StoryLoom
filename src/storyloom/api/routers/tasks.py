"""Task 配置管理 API（数据库 CRUD）

数据存储在 task_configs 表，字段与 CrewAI 的 Task 配置一致：
description / expected_output / agent_key / context_keys / position。
"""

from fastapi import APIRouter, HTTPException, status
from typing import Any, Dict

from storyloom.api.schemas import (
    TaskConfigInput,
    TaskConfigUpdate,
    TaskConfigView,
    TaskListResponse,
)
from storyloom.db import get_repository

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# 允许显式置空的字段（用于解除 Agent 绑定）
_NULLABLE_FIELDS = {"agent_key"}


def _repo():
    repo = get_repository()
    # 保证首次请求前已建表并导入种子数据
    repo.ensure_seeded()
    return repo


def _check_agent_exists(repo, agent_key) -> None:
    if agent_key and repo.get_agent(agent_key) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"引用的 Agent 不存在: {agent_key}",
        )


@router.get("/", response_model=TaskListResponse)
async def list_tasks():
    return TaskListResponse(tasks=_repo().list_tasks())


@router.post(
    "/",
    response_model=TaskConfigView,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(task: TaskConfigInput):
    repo = _repo()
    if repo.get_task(task.key) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task 已存在: {task.key}",
        )
    _check_agent_exists(repo, task.agent_key)

    payload: Dict[str, Any] = {
        key: value
        for key, value in task.model_dump().items()
        if key != "key" and value is not None
    }
    return repo.upsert_task(task.key, **payload)


@router.get("/{key}", response_model=TaskConfigView)
async def get_task(key: str):
    record = _repo().get_task(key)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task 不存在: {key}",
        )
    return record


@router.put("/{key}", response_model=TaskConfigView)
async def update_task(key: str, patch: TaskConfigUpdate):
    repo = _repo()
    existing = repo.get_task(key)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task 不存在: {key}",
        )

    payload = patch.model_dump(exclude_unset=True)
    _check_agent_exists(repo, payload.get("agent_key"))
    payload = {
        name: value
        for name, value in payload.items()
        if value is not None or name in _NULLABLE_FIELDS
    }
    if not payload:
        return existing
    return repo.upsert_task(key, **payload)


@router.delete("/{key}")
async def delete_task(key: str):
    if not _repo().delete_task(key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task 不存在: {key}",
        )
    return {"status": "ok", "key": key}
