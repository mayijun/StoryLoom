"""Task 配置管理 API（数据库 CRUD）

数据存储在 task_configs 表，按小说项目（project_id）隔离，
字段与 CrewAI 的 Task 配置一致：
description / expected_output / agent_key / context_keys / position。
"""

from fastapi import APIRouter, HTTPException, Query, status
from typing import Any, Dict

from storyloom.api.schemas import (
    TaskConfigInput,
    TaskConfigUpdate,
    TaskConfigView,
    TaskListResponse,
)
from storyloom.db import DEFAULT_PROJECT_ID, get_repository

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# 允许显式置空的字段（用于解除 Agent 绑定）
_NULLABLE_FIELDS = {"agent_key"}


def _repo(project_id: str):
    repo = get_repository()
    # 保证首次请求前已建表，并为该项目导入默认配置
    repo.ensure_seeded(project_id)
    return repo


def _check_agent_exists(repo, agent_key, project_id: str) -> None:
    if agent_key and repo.get_agent(agent_key, project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"引用的 Agent 不存在: {agent_key}",
        )


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    project_id: str = Query(DEFAULT_PROJECT_ID, description="小说项目 ID"),
):
    return TaskListResponse(tasks=_repo(project_id).list_tasks(project_id))


@router.post(
    "/",
    response_model=TaskConfigView,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    task: TaskConfigInput,
    project_id: str = Query(DEFAULT_PROJECT_ID, description="小说项目 ID"),
):
    repo = _repo(project_id)
    if repo.get_task(task.key, project_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task 已存在: {task.key}",
        )
    _check_agent_exists(repo, task.agent_key, project_id)

    payload: Dict[str, Any] = {
        key: value
        for key, value in task.model_dump().items()
        if key != "key" and value is not None
    }
    return repo.upsert_task(task.key, project_id=project_id, **payload)


@router.get("/{key}", response_model=TaskConfigView)
async def get_task(
    key: str,
    project_id: str = Query(DEFAULT_PROJECT_ID, description="小说项目 ID"),
):
    record = _repo(project_id).get_task(key, project_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task 不存在: {key}",
        )
    return record


@router.put("/{key}", response_model=TaskConfigView)
async def update_task(
    key: str,
    patch: TaskConfigUpdate,
    project_id: str = Query(DEFAULT_PROJECT_ID, description="小说项目 ID"),
):
    repo = _repo(project_id)
    existing = repo.get_task(key, project_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task 不存在: {key}",
        )

    payload = patch.model_dump(exclude_unset=True)
    _check_agent_exists(repo, payload.get("agent_key"), project_id)
    payload = {
        name: value
        for name, value in payload.items()
        if value is not None or name in _NULLABLE_FIELDS
    }
    if not payload:
        return existing
    return repo.upsert_task(key, project_id=project_id, **payload)


@router.delete("/{key}")
async def delete_task(
    key: str,
    project_id: str = Query(DEFAULT_PROJECT_ID, description="小说项目 ID"),
):
    if not _repo(project_id).delete_task(key, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task 不存在: {key}",
        )
    return {"status": "ok", "key": key}
