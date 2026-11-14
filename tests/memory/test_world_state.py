"""世界状态改写与模式切换测试（无需 API Key）。"""

from storyloom.memory.state import FactOverride


def test_override_audit(world):
    override = FactOverride(
        target="国王",
        field="emotion",
        after="恐惧",
        reason="剧情需要",
    )
    new_world, record = world.apply_override(override, snapshot_id="snap_1")
    assert new_world.characters["国王"].emotion == "恐惧"
    assert record.before == "平静"
    assert new_world.overrides[0]["after"] == "恐惧"
    assert new_world.flags["needs_review:国王"] is True


def test_mode_switch_writes_checkpoint(world):
    new_state = world.switch_mode("director", checkpoint_id="save_switch")
    assert new_state.mode == "director"
    assert new_state.flags["force_director_frame"] is True
    assert new_state.flags["last_checkpoint_id"] == "save_switch"
    assert world.mode == "game"  # 原状态不被原地修改
