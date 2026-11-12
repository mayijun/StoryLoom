"""双模式统一分层记忆测试（无需 API Key）"""

import pytest

from storyloom.db import CrewConfigRepository
from storyloom.memory import LayeredMemory, MemoryIndexer
from storyloom.memory.models import CharacterAsset, LocationAsset, NovelProject


@pytest.fixture
def repo(tmp_path):
    return CrewConfigRepository(f"sqlite:///{tmp_path / 'memory.db'}")


def test_layered_memory_separates_core_prompt_and_world_book(repo):
    memory = LayeredMemory("test_project", repo=repo)
    memory.configure_working(
        location="雾港旅店",
        present_characters=["林夏", "阿泽"],
        scene_brief="调查墙上的航海图",
    )
    memory.add_scene(scene_index=1, prose="林夏进入旅店，与阿泽会合。")
    memory.add_archive_item("lore:map", "航海图标出了雾港北侧的暗礁。")

    block = memory.prompt_block()
    assert "雾港旅店" in block
    assert "林夏, 阿泽" in block
    assert "林夏进入旅店" in block
    assert "北侧的暗礁" not in block

    retrieved = memory.retrieval_block("航海图", k=3)
    assert "北侧的暗礁" in retrieved


def test_director_flow_retrieves_world_book_from_layered_memory(repo):
    project = NovelProject(
        project_id="x", title="t", style="wuxia", characters=[], locations=[]
    )
    memory = LayeredMemory("x", repo=repo)
    memory.add_archive_item("lore:map", "航海图藏在雾港旅店的地下室。")

    context = memory.retrieval_block("导演要求角色寻找航海图", k=3)

    assert "航海图藏在雾港旅店的地下室" in context
    assert memory.items["lore:map"].hits == 1


def test_backfill_refreshes_assets_without_overwriting_layered_scenes(repo):
    memory = LayeredMemory("test_project", repo=repo)
    memory.add_scene(scene_index=1, prose="已生成的正文", key="scene_1")
    memory.add_archive_item("char:旧名", "旧名：已离场。动机：无")
    memory.add_archive_item(
        "secret:林夏", "林夏的秘密：旧秘密", visibility="private:林夏"
    )
    memory.add_archive_item("loc:旧港", "旧港：已废弃")
    memory.add_archive_item("lore:keep", "不应被清理的设定")

    MemoryIndexer(memory).backfill(
        scenes=[{"scene_id": "scene_1", "prose": "数据库中的旧正文"}],
        characters=[CharacterAsset(
            name="林夏", importance_tier="primary", persona="冷静", motivation="寻亲"
        )],
        locations=[LocationAsset(name="雾港", description="常年多雾")],
    )

    assert memory.items["scene:scene_1"].tier == "short_term"
    assert memory.items["scene:scene_1"].text == "已生成的正文"
    assert memory.items["char:林夏"].text == "林夏：冷静。动机：寻亲"
    assert memory.items["loc:雾港"].text == "雾港：常年多雾"

    # 已从数据库资产中移除的条目会被清理，其他归档项不受影响
    assert "char:旧名" not in memory.items
    assert "secret:林夏" not in memory.items
    assert "loc:旧港" not in memory.items
    assert "lore:keep" in memory.items
    stored = {row["id"] for row in repo.list_memory_items("test_project")}
    assert "test_project::char:旧名" not in stored

    # 未传入的资产类别不参与回填，因此也不清理
    MemoryIndexer(memory).backfill(scenes=[])
    assert "char:林夏" in memory.items
    assert "loc:雾港" in memory.items
