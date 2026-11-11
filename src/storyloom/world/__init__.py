"""世界层：状态、裁决协议与导演改写。

ActionProposal / AdjudicationResult / FactOverride 等公共协议统一在
storyloom.world.state 中定义，供 crews / flows / api 各层直接 import。
"""

from storyloom.world.state import (
    ActionProposal,
    AdjudicationResult,
    ArcState,
    CharState,
    Fact,
    FactOverride,
    LocationState,
    Promise,
    StateDelta,
    WorldEvent,
    WorldState,
)

__all__ = [
    "ActionProposal",
    "AdjudicationResult",
    "ArcState",
    "CharState",
    "Fact",
    "FactOverride",
    "LocationState",
    "Promise",
    "StateDelta",
    "WorldEvent",
    "WorldState",
]
