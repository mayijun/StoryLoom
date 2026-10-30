"""Task 配置 API 的数据库 CRUD 测试（不启动 HTTP 服务）"""

import asyncio

import pytest
from fastapi import HTTPException

from storyloom.api.schemas import TaskConfigInput, TaskConfigUpdate
from storyloom.db import reset_engines, reset_repositories


@pytest.fixture
def tasks_api(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STORYLOOM_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}"
    )
    reset_repositories()
    reset_engines()

    from storyloom.api.routers import tasks

    yield tasks

    reset_repositories()
    reset_engines()


def test_list_tasks_comes_from_database(tasks_api):
    response = asyncio.run(tasks_api.list_tasks())
    keys = [task.key for task in response.tasks]

    assert len(keys) == 6
    assert "prose_polish" in keys


def test_create_conflict_and_get(tasks_api):
    created = asyncio.run(
        tasks_api.create_task(
            TaskConfigInput(
                key="style_review",
                description="审查文风",
                expected_output="问题清单",
                agent_key="director",
            )
        )
    )
    assert created["key"] == "style_review"
    assert created["position"] > 0
    assert created["context_keys"] == []

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            tasks_api.create_task(
                TaskConfigInput(
                    key="style_review",
                    description="重复",
                    expected_output="重复",
                )
            )
        )
    assert exc_info.value.status_code == 409

    fetched = asyncio.run(tasks_api.get_task("style_review"))
    assert fetched["description"] == "审查文风"


def test_create_rejects_unknown_agent(tasks_api):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            tasks_api.create_task(
                TaskConfigInput(
                    key="bad_task",
                    description="描述",
                    expected_output="产物",
                    agent_key="not_exists",
                )
            )
        )
    assert exc_info.value.status_code == 400


def test_update_and_delete(tasks_api):
    asyncio.run(
        tasks_api.create_task(
            TaskConfigInput(
                key="style_review",
                description="审查文风",
                expected_output="问题清单",
            )
        )
    )

    updated = asyncio.run(
        tasks_api.update_task(
            "style_review",
            TaskConfigUpdate(
                enabled=False,
                agent_key="director",
                context_keys=["prose_polish"],
            ),
        )
    )
    assert updated["enabled"] is False
    assert updated["agent_key"] == "director"
    assert updated["context_keys"] == ["prose_polish"]

    cleared = asyncio.run(
        tasks_api.update_task("style_review", TaskConfigUpdate(agent_key=None))
    )
    assert cleared["agent_key"] is None

    asyncio.run(tasks_api.delete_task("style_review"))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(tasks_api.get_task("style_review"))
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            tasks_api.update_task(
                "style_review", TaskConfigUpdate(description="x")
            )
        )
    assert exc_info.value.status_code == 404
