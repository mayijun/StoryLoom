"""Agent 配置 API 的数据库 CRUD 测试（不启动 HTTP 服务）"""

import asyncio

import pytest
from fastapi import HTTPException

from storyloom.api.schemas import AgentConfigInput, AgentConfigUpdate
from storyloom.db import reset_engines, reset_repositories


@pytest.fixture
def agents_api(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STORYLOOM_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}"
    )
    reset_repositories()
    reset_engines()

    from storyloom.api.routers import agents

    yield agents

    reset_repositories()
    reset_engines()


def test_list_agents_comes_from_database(agents_api):
    response = asyncio.run(agents_api.list_agents())
    keys = [agent.key for agent in response.agents]

    assert len(keys) == 8
    assert keys[0] == "protagonist"
    assert isinstance(response.available_models, list)


def test_create_conflict_and_get(agents_api):
    created = asyncio.run(
        agents_api.create_agent(
            AgentConfigInput(
                key="critic",
                role="文风批评家",
                goal="挑出陈词滥调",
                backstory="你是苛刻的编辑",
            )
        )
    )
    assert created["key"] == "critic"
    assert created["crew"] == "scene_crew"
    assert created["position"] > 0

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            agents_api.create_agent(
                AgentConfigInput(
                    key="critic", role="重复", goal="重复", backstory="重复"
                )
            )
        )
    assert exc_info.value.status_code == 409

    fetched = asyncio.run(agents_api.get_agent("critic"))
    assert fetched["goal"] == "挑出陈词滥调"


def test_update_merges_settings_and_delete(agents_api):
    asyncio.run(
        agents_api.create_agent(
            AgentConfigInput(
                key="critic",
                role="文风批评家",
                goal="挑刺",
                backstory="背景",
                settings={"max_rpm": 30},
            )
        )
    )

    updated = asyncio.run(
        agents_api.update_agent(
            "critic",
            AgentConfigUpdate(goal="更严格", settings={"reasoning": True}),
        )
    )
    assert updated["goal"] == "更严格"
    assert updated["settings"] == {"max_rpm": 30, "reasoning": True}

    asyncio.run(agents_api.delete_agent("critic"))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(agents_api.get_agent("critic"))
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(agents_api.update_agent("critic", AgentConfigUpdate(goal="x")))
    assert exc_info.value.status_code == 404
