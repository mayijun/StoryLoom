"""双模式统一分层记忆测试（无需 API Key）"""

import pytest

from storyloom.db import CrewConfigRepository
from storyloom.memory import LayeredMemory, MemoryIndexer, VectorBackend
from storyloom.memory.models import (
    CharacterAsset,
    Foreshadowing,
    LocationAsset,
    NovelProject,
)


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


def test_add_condensed_writes_requested_tier_with_scope(repo):
    memory = LayeredMemory("p_cond", repo=repo)
    long_item = memory.add_condensed(
        "long_term",
        "林晚确认老周替人转移货物，码头线索坐实。",
        scene_index=3,
        visible_to=["林晚", "老周"],
        tags=["side_stage"],
        source="side_stage",
    )
    key_item = memory.add_condensed(
        "key_events",
        "老周向走私船转移关键木箱，被林晚目击。",
        scene_index=3,
        visible_to=["林晚", "老周"],
    )

    assert long_item.tier == "long_term"
    assert key_item.tier == "key_events"
    assert long_item.visible_to == ["林晚", "老周"]
    assert long_item.last_hit_scene == 3

    assert "林晚确认老周" in memory.prompt_block(viewer="林晚")
    assert "林晚确认老周" not in memory.prompt_block(viewer="李四")

    # 重启后仍停留在导演指定的层
    reloaded = LayeredMemory("p_cond", repo=repo)
    assert reloaded.items[long_item.id].tier == "long_term"
    assert reloaded.items[key_item.id].tier == "key_events"


def test_pending_side_stage_is_hidden_from_world_book_retrieval(repo):
    memory = LayeredMemory("p_pending", repo=repo)
    memory.add_archive_item(
        "side_stage_pending:asp_1",
        '{"focus": "林晚", "reason": "确认码头目击者"}',
        tags=["side_stage_pending"],
        visible_to=[],
        source="side_stage_pending",
    )

    assert memory.retrieval_block("码头目击者", viewer="director") == ""
    assert memory.retrieval_block("码头目击者") == ""


def test_scene_memory_scopes_by_witnesses_and_crowd(repo):
    memory = LayeredMemory("p_scope", repo=repo)
    memory.add_scene(
        1, "张三在密室看见钥匙。", present_characters=["张三"]
    )
    memory.add_scene(
        2, "广场上公开宣读告示。",
        present_characters=["张三"], crowd=True,
    )

    assert "钥匙" in memory.prompt_block(viewer="张三")
    assert "钥匙" not in memory.prompt_block(viewer="李四")
    assert "钥匙" in memory.prompt_block(viewer="director")
    assert "告示" in memory.prompt_block(viewer="张三")
    assert "告示" in memory.prompt_block(viewer="crowd")
    assert "告示" not in memory.prompt_block(viewer="李四")


def test_backfill_refreshes_assets_without_overwriting_layered_scenes(repo):
    memory = LayeredMemory("test_project", repo=repo)
    memory.add_scene(scene_index=1, prose="已生成的正文", key="scene_1")
    memory.add_archive_item("char:旧名", "旧名：已离场。动机：无")
    memory.add_archive_item(
        "secret:林夏", "林夏的秘密：旧秘密",
        visible_to=["林夏"],
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
    # 秘密是独立记忆条目：角色仍存在时不应被回填清理
    assert "secret:林夏" in memory.items
    assert "loc:旧港" not in memory.items
    assert "lore:keep" in memory.items
    stored = {row["id"] for row in repo.list_memory_items("test_project")}
    assert "test_project::char:旧名" not in stored

    # 未传入的资产类别不参与回填，因此也不清理
    MemoryIndexer(memory).backfill(scenes=[])
    assert "char:林夏" in memory.items
    assert "loc:雾港" in memory.items


def test_world_book_matching_respects_viewer_across_backends(repo):
    secret_text = "林夏是前朝公主，身上有王室胎记。"

    def embed(text: str):
        return [1.0 if "前朝" in text else 0.0, 1.0]

    backends = [
        ("fts", {}),
        ("hybrid", {}),
        ("vector", {"vector": VectorBackend(embed)}),
    ]
    for backend, kwargs in backends:
        memory = LayeredMemory(
            f"p_viewer_{backend}", repo=repo, backend=backend, **kwargs
        )
        memory.add_archive_item(
            "secret:林夏",
            secret_text,
            visible_to=["林夏"],
            source="asset",
        )
        assert "前朝公主" in memory.retrieval_block(
            "前朝公主", viewer="林夏"
        )
        assert memory.retrieval_block("前朝公主", viewer="阿泽") == ""
        assert "前朝公主" in memory.retrieval_block(
            "前朝公主", viewer="director"
        )


def test_sync_foreshadowings_preserves_later_visible_to(repo):
    memory = LayeredMemory("p_fs_union", repo=repo)
    fs = Foreshadowing(
        description="旧航海图",
        planted_in_scene="scene_1",
        target_revelation="航海图指向密道入口",
        visible_to=["林夏"],
    )
    memory.sync_foreshadowings([fs])
    truth_id = f"foreshadow_truth:{fs.foreshadow_id}"
    assert memory.items[truth_id].visible_to == ["林夏"]

    # 后续阿泽得知真相：资产侧 visible_to 为空也不应覆盖记忆侧
    fs.visible_to = []
    memory.items[truth_id].visible_to = ["林夏", "阿泽"]
    memory._put(memory.items[truth_id])
    memory.sync_foreshadowings([fs])
    assert set(memory.items[truth_id].visible_to) == {"林夏", "阿泽"}

    memory.sync_foreshadowings([])
    assert truth_id not in memory.items
    assert f"foreshadow:{fs.foreshadow_id}" not in memory.items
