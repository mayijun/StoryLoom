"""记忆可见性与秘密隔离测试（无需 API Key）。"""

from storyloom.memory import LayeredMemory, MemoryItem
from storyloom.memory.models import Foreshadowing
from storyloom.memory.state import Fact


def test_legacy_known_by_migrates_to_visible_to():
    """旧快照 / 旧行里的 visibility + known_by 读取时统一为 visible_to。"""
    restricted = MemoryItem.from_row(
        {
            "id": "legacy:restricted",
            "visibility": "restricted",
            "known_by": ["张三", "gm"],
        }
    )
    assert restricted.visible_to == ["张三"]

    public = MemoryItem.from_row(
        {"id": "legacy:public", "visibility": "public", "known_by": []}
    )
    assert public.visible_to == ["all"]

    private = MemoryItem.from_row(
        {"id": "legacy:private", "visibility": "private:李四"}
    )
    assert private.visible_to == ["李四"]

    # 完全没有可见性字段的旧行按公开处理
    missing = MemoryItem.from_row({"id": "legacy:missing"})
    assert missing.visible_to == ["all"]

    snapshot = MemoryItem.model_validate(
        {"id": "snap", "known_by": ["王五"], "visibility": "restricted"}
    )
    assert snapshot.visible_to == ["王五"]


def test_legacy_fact_and_foreshadow_migrate_visibility():
    fact = Fact.model_validate(
        {
            "subject": "玩家",
            "predicate": "见过",
            "object": "国王",
            "known_by": ["玩家", "gm"],
        }
    )
    assert fact.visible_to == {"玩家"}

    foreshadow = Foreshadowing.model_validate(
        {
            "description": "旧航海图",
            "planted_in_scene": "scene_1",
            "target_revelation": "指向密道",
            "visibility": "restricted",
            "known_by": ["林夏", "gm"],
        }
    )
    assert foreshadow.visible_to == ["林夏"]

    hidden = Foreshadowing.model_validate(
        {
            "description": "无名伏笔",
            "planted_in_scene": "scene_2",
            "target_revelation": "无人知晓",
            "visibility": "restricted",
            "known_by": [],
        }
    )
    assert hidden.visible_to == []


def test_fact_visibility_filters_by_visible_to(world):
    fact = Fact(
        subject="玩家",
        predicate="经历",
        object="曾在北境见过国王",
        visible_to={"玩家", "gm"},
    )
    world.facts[fact.id] = fact

    player_view = world.view("玩家")
    guard_view = world.view("侍卫长")
    assert any(f["id"] == fact.id for f in player_view["facts"])
    assert all(f["id"] != fact.id for f in guard_view["facts"])


def test_multi_viewer_fact_projection_and_sync(repo, world):
    """多个知情者不等于公开；新增知情者后原地更新同一条记忆。"""
    fact = Fact(
        subject="玩家",
        predicate="经历",
        object="曾在北境见过国王",
        visible_to={"玩家", "国王", "gm"},
    )
    world.facts[fact.id] = fact

    memory = LayeredMemory("p_multi_viewer", repo=repo)
    memory.sync_world_state(world, current_scene=1)
    item = memory.items[f"ws:fact:{fact.id}"]
    assert item.visible_to == ["国王", "玩家"]
    assert "经历" in memory.prompt_block(viewer="玩家")
    assert "经历" in memory.prompt_block(viewer="国王")
    assert "经历" not in memory.prompt_block(viewer="侍卫长")

    fact.visible_to.add("侍卫长")
    memory.sync_world_state(world, current_scene=2)
    item = memory.items[f"ws:fact:{fact.id}"]
    assert "侍卫长" in item.visible_to
    assert "经历" in memory.prompt_block(viewer="侍卫长")


def test_secrets_visibility(repo):
    memory = LayeredMemory("p_secrets", repo=repo)
    memory.add_archive_item(
        "secret:玩家",
        "你的真实身份是王室的私生子。",
        tags=["secret", "asset"],
        visible_to=["玩家"],
        source="asset",
    )
    memory.add_archive_item(
        "secret:国王",
        "父亲失踪与你有关。",
        tags=["secret", "asset"],
        visible_to=["国王"],
        source="asset",
    )
    assert memory.retrieve("私生子", viewer="国王") == []
    assert [i.id for i in memory.retrieve("私生子", viewer="玩家")] == [
        "secret:玩家"
    ]
    assert [i.id for i in memory.retrieve("私生子", viewer="director")] == [
        "secret:玩家"
    ]
    assert "私生子" not in memory.prompt_block(viewer="国王")


def test_character_secret_stored_only_in_memory(repo):
    repo.upsert_character(
        "p_secret",
        "林夏",
        "primary",
        "冷静",
        "寻亲",
        secrets="她是前朝公主。",
    )
    characters = repo.list_characters("p_secret")
    assert "secrets" not in characters[0]

    items = repo.list_memory_items("p_secret")
    secret = next(
        item for item in items if item["id"].endswith("::secret:林夏")
    )
    assert secret["text"] == "她是前朝公主。"
    assert secret["visible_to"] == ["林夏"]

    repo.upsert_character(
        "p_secret", "林夏", "primary", "冷静", "寻亲", secrets=""
    )
    assert not any(
        item["id"].endswith("::secret:林夏")
        for item in repo.list_memory_items("p_secret")
    )


def test_foreshadow_truth_visible_to_director_and_known_character(repo):
    memory = LayeredMemory("p_fs", repo=repo)
    fs = Foreshadowing(
        description="旅店墙上的旧航海图",
        planted_in_scene="scene_1",
        target_revelation="航海图指向王室密道",
        visible_to=["林夏"],
    )
    memory.sync_foreshadowings([fs])

    truth_id = f"foreshadow_truth:{fs.foreshadow_id}"
    assert [i.id for i in memory.retrieve("王室密道", viewer="林夏")] == [
        truth_id
    ]
    assert memory.retrieve("王室密道", viewer="阿泽") == []
    assert [
        i.id for i in memory.retrieve("王室密道", viewer="director")
    ] == [truth_id]
    # 描述与真相共享 scope：不知情角色也检索不到线索
    assert memory.retrieve("航海图", viewer="阿泽") == []
