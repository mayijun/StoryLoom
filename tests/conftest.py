"""跨模块测试共用的项目与世界状态夹具。"""

import pytest

from storyloom.db import CrewConfigRepository, reset_engines, reset_repositories
from storyloom.memory.models import CharacterAsset, LocationAsset, NovelProject
from storyloom.memory.state import WorldState


@pytest.fixture
def repo(tmp_path):
    reset_repositories()
    reset_engines()
    url = f"sqlite:///{tmp_path / 'storyloom.db'}"
    yield CrewConfigRepository(url)
    reset_repositories()
    reset_engines()


@pytest.fixture
def project():
    return NovelProject(
        project_id="world_demo",
        title="雾港疑云",
        style="film_narrative",
        characters=[
            CharacterAsset(
                name="玩家",
                importance_tier="primary",
                persona="刚回到雾港的陌生人",
                motivation="查清父亲失踪的真相",
            ),
            CharacterAsset(
                name="国王",
                importance_tier="primary",
                persona="声音不高",
                motivation="守住王位",
            ),
            CharacterAsset(
                name="侍卫长",
                importance_tier="secondary",
                persona="甲胄不离身",
                motivation="保护国王",
            ),
            CharacterAsset(
                name="旅店老板",
                importance_tier="background",
                persona="一边擦杯子一边观察客人",
                motivation="把小店开下去",
            ),
        ],
        locations=[
            LocationAsset(name="雾港旅店", description="潮湿的木楼"),
            LocationAsset(name="码头", description="缆绳与鱼腥味"),
            LocationAsset(name="王宫", description="白色石阶"),
            LocationAsset(name="地牢", description="石壁渗水"),
        ],
    )


@pytest.fixture
def world(project):
    state = WorldState.from_project(project)
    state.locations["雾港旅店"].exits = {"码头": 10}
    state.locations["码头"].exits = {"雾港旅店": 10, "王宫": 20}
    state.locations["王宫"].exits = {"码头": 20, "地牢": 5}
    state.locations["地牢"].exits = {"王宫": 5}
    return state
