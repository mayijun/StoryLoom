"""存档、读档与回放测试（无需 API Key）。"""

from storyloom.memory.checkpoint import SaveService, state_from_save
from storyloom.memory.state import StageDirective, StageScene


def test_save_load_replay_is_identical(tmp_path, world):
    scene = StageScene(
        directives=[StageDirective(kind="say", params={"text": "雾从海面压下来。"})],
        text="雾从海面压下来。",
        choices=[{"index": 0, "label": "前往码头"}],
    )
    service = SaveService(root=str(tmp_path / "saves"))
    record = service.save("world_demo", world, scene, label="测试存档")

    loaded = service.load("world_demo", record.save_id)
    replayed = service.replay("world_demo", record.save_id)

    assert replayed.text == scene.text
    assert replayed.directives == [
        d.model_dump(mode="json") for d in scene.directives
    ]
    assert state_from_save(loaded).model_dump() == world.model_dump()
    assert [s.save_id for s in service.list("world_demo")] == [record.save_id]
