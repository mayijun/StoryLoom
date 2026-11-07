"""Agent / Task 配置导入导出与跨项目复制 API

导出为可移植 JSON 快照；导入按 key upsert（merge）或先清空再写入
（overwrite）。跨项目复制 = 读取源项目配置 + 对目标项目执行导入。
导入后清理该项目的 Crew 缓存，使下一次生成使用新配置。
"""

from fastapi import APIRouter, HTTPException

from storyloom.api.schemas import ConfigCopyRequest, ConfigExport, ConfigImport
from storyloom.api.engine import engine
from storyloom.db import get_repository

router = APIRouter(prefix="/api/projects/{project_id}/config", tags=["config"])

_AGENT_EXPORT_FIELDS = (
    "key", "role", "goal", "backstory",
    "allow_delegation", "verbose", "max_iter", "settings",
    "enabled", "position",
)
_TASK_EXPORT_FIELDS = (
    "key", "description", "expected_output",
    "agent_key", "context_keys", "enabled", "position",
)
_AGENT_REQUIRED = {"role", "goal", "backstory"}
_TASK_REQUIRED = {"description", "expected_output"}


def _export_config(project_id: str) -> ConfigExport:
    repo = get_repository()
    repo.ensure_seeded(project_id)
    agents = [
        {k: v for k, v in a.items() if k in _AGENT_EXPORT_FIELDS}
        for a in repo.list_agents(project_id)
    ]
    tasks = [
        {k: v for k, v in t.items() if k in _TASK_EXPORT_FIELDS}
        for t in repo.list_tasks(project_id)
    ]
    return ConfigExport(project_id=project_id, agents=agents, tasks=tasks)


def _apply_import(project_id: str, data: ConfigImport) -> dict:
    repo = get_repository()
    if not repo.project_exists(project_id):
        raise HTTPException(404, "Project not found")

    # 校验必填字段，避免半成品配置写库
    for a in data.agents:
        missing = _AGENT_REQUIRED - {k for k, v in a.items() if v}
        if not a.get("key") or missing:
            raise HTTPException(
                422, f"Agent 配置缺少必填字段: key={a.get('key')!r} {sorted(missing)}"
            )
    for t in data.tasks:
        missing = _TASK_REQUIRED - {k for k, v in t.items() if v}
        if not t.get("key") or missing:
            raise HTTPException(
                422, f"Task 配置缺少必填字段: key={t.get('key')!r} {sorted(missing)}"
            )
    # 仓储约定：项目「零 Agent」会在下一次读取时自动重播种 YAML 默认配置，
    # 因此 overwrite 不允许导入空 Agent 列表（否则清空后立即被重种子覆盖）。
    if data.mode == "overwrite" and not data.agents:
        raise HTTPException(
            422, "overwrite 模式至少需要一个 Agent（项目不允许零 Agent 配置）"
        )

    # 先 upsert 再删除多余项：保证 overwrite 过程中项目始终有 Agent，
    # 不会触发仓储的自动重播种。
    for a in data.agents:
        payload = {k: v for k, v in a.items() if k != "key" and v is not None}
        repo.upsert_agent(a["key"], project_id=project_id, **payload)
    for t in data.tasks:
        payload = {k: v for k, v in t.items() if k != "key" and v is not None}
        repo.upsert_task(t["key"], project_id=project_id, **payload)

    if data.mode == "overwrite":
        keep_agents = {a["key"] for a in data.agents}
        keep_tasks = {t["key"] for t in data.tasks}
        for a in repo.list_agents(project_id):
            if a["key"] not in keep_agents:
                repo.delete_agent(a["key"], project_id)
        for t in repo.list_tasks(project_id):
            if t["key"] not in keep_tasks:
                repo.delete_task(t["key"], project_id)

    # 让缓存的 Crew 在下一次生成时按新配置重建
    engine.crews.pop(project_id, None)
    return {
        "status": "ok",
        "project_id": project_id,
        "mode": data.mode,
        "agents": len(data.agents),
        "tasks": len(data.tasks),
    }


@router.get("/export", response_model=ConfigExport)
async def export_config(project_id: str):
    repo = get_repository()
    if not repo.project_exists(project_id):
        raise HTTPException(404, "Project not found")
    return _export_config(project_id)


@router.post("/import")
async def import_config(project_id: str, data: ConfigImport):
    return _apply_import(project_id, data)


@router.post("/copy_from")
async def copy_config_from(project_id: str, data: ConfigCopyRequest):
    repo = get_repository()
    if not repo.project_exists(project_id):
        raise HTTPException(404, "Project not found")
    if not repo.project_exists(data.source_project_id):
        raise HTTPException(404, f"源项目不存在: {data.source_project_id}")
    if data.source_project_id == project_id:
        raise HTTPException(400, "源项目与目标项目相同")
    exported = _export_config(data.source_project_id)
    return _apply_import(
        project_id,
        ConfigImport(
            agents=exported.agents, tasks=exported.tasks, mode=data.mode
        ),
    )
