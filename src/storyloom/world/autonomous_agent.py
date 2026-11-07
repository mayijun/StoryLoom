"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

NPC 自主：记忆 → 反思 → 计划 → 提案。

纪律：
- NPC 只能产出 ActionProposal，不能直接改 WorldState；
- 提案与玩家行动走同一条 GM 裁决链；
- 没有记忆/模型时退化为确定性提案，不阻塞回合。
"""

from typing import List, Optional, Tuple

from storyloom.memory.core import LayeredMemory
from storyloom.world.game_master import ActionProposal
from storyloom.world.state import WorldState

IDLE_THRESHOLD = 3


class AutonomousAgent:
    """一个 NPC 的最小自主循环"""

    def __init__(
        self,
        name: str,
        memory: Optional[LayeredMemory] = None,
        reflect_fn=None,
    ):
        self.name = name
        self.memory = memory
        self.reflect_fn = reflect_fn

    def reflect(self, state: WorldState) -> str:
        """读取自己的记忆视图（不要全局 WorldState）"""
        char = state.characters.get(self.name)
        if char is None:
            return ""
        recall = ""
        if self.memory is not None:
            recall = self.memory.retrieval_block(
                f"{self.name} {char.location}", viewer=self.name, k=2
            )
        if self.reflect_fn is not None:
            try:
                return str(self.reflect_fn(state.view(self.name), recall))
            except Exception:
                pass
        return (
            f"{self.name}在{char.location}，"
            f"情绪{char.emotion}，目标：{'、'.join(char.goals) or '观察局势'}"
            + (f"\n{recall}" if recall else "")
        )

    def plan(self, state: WorldState) -> List[str]:
        char = state.characters.get(self.name)
        if char is None:
            return []
        plans = ["了解周围发生了什么"]
        if char.goals:
            plans.insert(0, char.goals[0])
        return plans

    def propose(self, state: WorldState) -> List[ActionProposal]:
        """把计划变成可裁决的提案（不写状态）"""
        char = state.characters.get(self.name)
        if char is None or char.status != "active":
            return []
        player = state.characters.get("玩家")
        player_location = player.location if player else ""

        others = [
            name for name in state.characters_at(char.location)
            if name != self.name
        ]
        proposals: List[ActionProposal] = []

        if char.location == player_location and player is not None:
            proposals.append(
                ActionProposal(
                    actor=self.name,
                    kind="talk",
                    target="玩家",
                    detail=f"{self.name}主动与玩家搭话",
                    source="npc",
                )
            )
        elif others:
            proposals.append(
                ActionProposal(
                    actor=self.name,
                    kind="talk",
                    target=others[0],
                    detail=f"{self.name}与{others[0]}交谈",
                    source="npc",
                )
            )
        else:
            loc = state.locations.get(char.location)
            if loc and loc.exits:
                destination = next(iter(loc.exits))
                proposals.append(
                    ActionProposal(
                        actor=self.name,
                        kind="move",
                        target=destination,
                        detail=f"{self.name}前往{destination}",
                        source="npc",
                    )
                )
            else:
                proposals.append(
                    ActionProposal(
                        actor=self.name,
                        kind="observe",
                        detail=f"{self.name}观察四周",
                        source="npc",
                    )
                )
        return proposals


def autonomous_tick(
    state: WorldState,
    memory: Optional[LayeredMemory] = None,
    idle_turns: int = 0,
    threshold: int = IDLE_THRESHOLD,
) -> Tuple[List[ActionProposal], List[str]]:
    """静止若干回合后，让一个在场 NPC 自发行动。

    返回 (提案, 参与 NPC)；不改变状态。
    """
    if idle_turns < threshold:
        return [], []
    actor = state.characters.get("玩家")
    location = actor.location if actor else ""
    candidates = [
        name for name in state.characters_at(location) if name != "玩家"
    ]
    if not candidates:
        candidates = [
            name for name in state.characters
            if name != "玩家"
            and state.characters[name].status == "active"
        ]
    if not candidates:
        return [], []

    proposals: List[ActionProposal] = []
    actors: List[str] = []
    for name in candidates[:2]:
        agent = AutonomousAgent(name, memory=memory)
        items = agent.propose(state)
        if items:
            proposals.extend(items[:1])
            actors.append(name)
    return proposals, actors


__all__ = ["AutonomousAgent", "autonomous_tick", "IDLE_THRESHOLD"]
