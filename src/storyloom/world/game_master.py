"""
兼容层：GameMaster / ActionProposal / AdjudicationResult 等
已迁至 ``storyloom.crews.scene_crew.deterministic.gm``。

这里 re-export 以保持旧 import 路径 ``from storyloom.world.game_master import GameMaster`` 不 break。
新代码请用 ::

    from storyloom.crews.scene_crew.deterministic.gm import GameMaster, ActionProposal, AdjudicationResult
"""

from storyloom.crews.scene_crew.deterministic.gm import (
    GUARD_KEYWORDS,
    PRISON_LOCATION,
    ActionProposal,
    AdjudicationResult,
    GameMaster,
)

__all__ = [
    "GUARD_KEYWORDS",
    "PRISON_LOCATION",
    "ActionProposal",
    "AdjudicationResult",
    "GameMaster",
]
