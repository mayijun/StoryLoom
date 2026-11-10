"""世界层：状态、双模式权限与 NPC 自主。

注意：GM / ActionProposal / AdjudicationResult 已迁至
storyloom.crews.scene_crew.deterministic.gm，这里通过 __getattr__ 懒加载
以保持 world 包的公开 API 不变，同时避免 world.__init__ → gm → world.state
导致的循环导入。
"""

from storyloom.world.state import (
    ArcState,
    CharState,
    Fact,
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
    "GameMaster",
    "LocationState",
    "Promise",
    "StateDelta",
    "WorldEvent",
    "WorldState",
]

# 懒加载：避免循环导入 world.__init__ → gm → world.state
def __getattr__(name: str):
    if name in ("ActionProposal", "AdjudicationResult", "GameMaster"):
        from storyloom.crews.scene_crew.deterministic.gm import (
            ActionProposal,
            AdjudicationResult,
            GameMaster,
        )
        return {
            "ActionProposal": ActionProposal,
            "AdjudicationResult": AdjudicationResult,
            "GameMaster": GameMaster,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
