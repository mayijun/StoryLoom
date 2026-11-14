"""叙事引擎世界简报的可见性测试（无需 API Key）。"""

from storyloom.engine.narrative import NarrativeEngine
from storyloom.memory.state import Fact


def test_world_context_fog_hides_unseeable(project, world):
    """_world_context 对非全知 actor 只泄露 view() 可见内容。"""
    world.characters["玩家"].location = "雾港旅店"
    world.characters["国王"].location = "王宫"
    world.characters["侍卫长"].location = "王宫"
    world.flags["_gm_secret_layoff"] = True
    world.relationships["国王|侍卫长"] = 10
    world.relationships["玩家|旅店老板"] = 3
    hidden = Fact(
        subject="国王",
        predicate="秘密",
        object="准备逃亡",
        visible_to={"国王", "gm"},
    )
    world.facts[hidden.id] = hidden

    loop = NarrativeEngine(project=project)
    book = loop._world_context(world, "玩家")

    assert "王宫" not in book
    assert "地牢" not in book
    assert "_gm_secret_layoff" not in book
    assert "国王|侍卫长" not in book
    assert "准备逃亡" not in book

    assert "雾港旅店" in book
    assert "玩家" in book
    assert "玩家|旅店老板" in book


def test_world_context_gm_sees_everything(project, world):
    """GM actor 调用时 view() 自动全知，world_book 应包含所有信息。"""
    world.characters["玩家"].location = "雾港旅店"
    world.characters["国王"].location = "王宫"
    world.relationships["国王|侍卫长"] = 10
    hidden = Fact(
        subject="国王",
        predicate="秘密",
        object="准备逃亡",
        visible_to={"国王", "gm"},
    )
    world.facts[hidden.id] = hidden

    loop = NarrativeEngine(project=project)
    book = loop._world_context(world, "gm")

    assert "王宫" in book
    assert "地牢" in book
    assert "国王" in book
    assert "国王|侍卫长" in book
    assert "准备逃亡" in book
