"""叙事引擎回合运行时测试（无需 API Key）。"""

import asyncio

from storyloom.engine.narrative import NarrativeEngine


def test_idle_three_turns_triggers_npc_event(project, world):
    world.characters["玩家"].location = "王宫"
    world.characters["国王"].location = "王宫"
    world.characters["侍卫长"].location = "王宫"

    engine = NarrativeEngine(project=project)
    result = asyncio.run(
        engine.play_turn(
            project=project,
            world_state=world,
            wait=True,
            idle_turns=3,
        )
    )
    assert result.status == "ok"
    assert result.state_delta.events
    assert all(e.actor != "玩家" for e in result.state_delta.events)


def test_freeform_text_enters_narrative_pipeline_without_action_parser(
    project, world
):
    action = "把账单折成纸船，放进街角的积水里"
    engine = NarrativeEngine(project=project)
    result = asyncio.run(
        engine.play_turn(
            project=project,
            world_state=world,
            action_text=action,
        )
    )

    assert result.status == "ok"
    assert result.state.time_minutes == world.time_minutes + 1
    assert result.state_delta.events[-1].summary == action


def test_director_mode_turn_runs_without_touching_game_entry(project, world):
    engine = NarrativeEngine(project=project)
    result = asyncio.run(
        engine.play_turn(
            project=project,
            world_state=world,
            mode="director",
            goal="让雾更浓，压住码头的灯光。",
            action_text="让雾更浓",
        )
    )
    assert result.status == "ok"
    assert result.text
    assert result.state.mode == "director"
