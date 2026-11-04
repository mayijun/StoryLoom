"""Agent 配置 API 的数据库 CRUD 测试（不启动 HTTP 服务）

端点函数被直接调用（非 TestClient），Query 参数需显式传入。
"""

import asyncio

import pytest
from fastapi import HTTPException

from storyloom.api.schemas import AgentConfigInput, AgentConfigUpdate
from storyloom.db import reset_engines, reset_repositories

DEMO = "demo"


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
    response = asyncio.run(agents_api.list_agents(project_id=DEMO))
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
            ),
            project_id=DEMO,
        )
    )
    assert created["key"] == "critic"
    assert created["project_id"] == DEMO
    assert created["crew"] == "scene_crew"
    assert created["position"] > 0

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            agents_api.create_agent(
                AgentConfigInput(
                    key="critic", role="重复", goal="重复", backstory="重复"
                ),
                project_id=DEMO,
            )
        )
    assert exc_info.value.status_code == 409

    fetched = asyncio.run(agents_api.get_agent("critic", project_id=DEMO))
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
            ),
            project_id=DEMO,
        )
    )

    updated = asyncio.run(
        agents_api.update_agent(
            "critic",
            AgentConfigUpdate(goal="更严格", settings={"reasoning": True}),
            project_id=DEMO,
        )
    )
    assert updated["goal"] == "更严格"
    assert updated["settings"] == {"max_rpm": 30, "reasoning": True}

    asyncio.run(agents_api.delete_agent("critic", project_id=DEMO))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(agents_api.get_agent("critic", project_id=DEMO))
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            agents_api.update_agent(
                "critic", AgentConfigUpdate(goal="x"), project_id=DEMO
            )
        )
    assert exc_info.value.status_code == 404


def test_projects_have_isolated_agents(agents_api):
    """不同小说项目的 Agent 相互隔离，互不影响"""
    asyncio.run(
        agents_api.create_agent(
            AgentConfigInput(
                key="critic",
                role="demo 的批评家",
                goal="demo 目标",
                backstory="demo 背景",
            ),
            project_id=DEMO,
        )
    )

    # 另一个项目：没有 demo 新增的 critic，仍是一套默认配置
    other = asyncio.run(agents_api.list_agents(project_id="novel2"))
    assert len(other.agents) == 8
    assert "critic" not in [a.key for a in other.agents]

    # 修改 demo 的 director，不影响 novel2
    asyncio.run(
        agents_api.update_agent(
            "director",
            AgentConfigUpdate(backstory="demo 专属导演"),
            project_id=DEMO,
        )
    )
    demo_director = asyncio.run(
        agents_api.get_agent("director", project_id=DEMO)
    )
    other_director = asyncio.run(
        agents_api.get_agent("director", project_id="novel2")
    )
    assert demo_director["backstory"] == "demo 专属导演"
    assert other_director["backstory"] != "demo 专属导演"
