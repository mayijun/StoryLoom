"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

双模式权限策略：
- GameAuthority：GM 全权裁决，玩家与 NPC 同权；
- DirectorAuthority：导演指令优先，GM 降级为事实检查器，
  允许带审计与快照的 FactOverride 改写。
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol, Tuple

from pydantic import BaseModel, Field

from storyloom.world.game_master import (
    ActionProposal,
    AdjudicationResult,
    GameMaster,
)
from storyloom.world.state import CharState, LocationState, WorldState


class FactOverride(BaseModel):
    """导演改写事实的结构化留痕"""

    override_id: str = Field(
        default_factory=lambda: f"ovr_{uuid.uuid4().hex[:8]}"
    )
    target: str
    field: str
    before: Any = None
    after: Any = None
    reason: str = ""
    base_snapshot_id: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    rolled_back: bool = False


class AuthorityPolicy(Protocol):
    def adjudicate(
        self,
        proposal: ActionProposal,
        world: WorldState,
        frame: Any = None,
    ) -> AdjudicationResult: ...

    def may_write_state_directly(self, actor: str) -> bool: ...


class GameAuthority:
    """游戏模式：所有行动必须经 GM 裁决"""

    def __init__(self, gm: Optional[GameMaster] = None):
        self.gm = gm or GameMaster()

    def adjudicate(
        self,
        proposal: ActionProposal,
        world: WorldState,
        frame: Any = None,
    ) -> AdjudicationResult:
        return self.gm.adjudicate(proposal, world)

    def may_write_state_directly(self, actor: str) -> bool:
        return False


class DirectorAuthority:
    """导演模式：指令优先，改写必须走 FactOverride"""

    def __init__(self, gm: Optional[GameMaster] = None):
        self.gm = gm or GameMaster()

    def adjudicate(
        self,
        proposal: ActionProposal,
        world: WorldState,
        frame: Any = None,
    ) -> AdjudicationResult:
        """导演指令不做可行性否决；GM 只检查事实是否存在。"""
        if proposal.kind == "other":
            return AdjudicationResult(
                success=True,
                outcome="directed",
                narrative=proposal.detail
                or (frame.goal if frame is not None else ""),
                rule="director_authority",
            )
        result = self.gm.adjudicate(proposal, world)
        # 导演模式下 GM 失败只作为事实提示，不阻断指令
        result.state_delta = result.state_delta
        return result

    def may_write_state_directly(self, actor: str) -> bool:
        return actor in ("director", "narrator")

    def apply_override(
        self,
        override: FactOverride,
        world: WorldState,
        snapshot_id: str = "",
    ) -> Tuple[WorldState, FactOverride]:
        """执行改写：自动记录 before / after，并标记连带复核"""
        new = world.model_copy(deep=True)
        before = self._read_field(new, override.target, override.field)
        record = override.model_copy(
            update={
                "before": before,
                "base_snapshot_id": snapshot_id,
            }
        )
        self._write_field(new, record.target, record.field, record.after)
        new.overrides.append(record.model_dump(mode="json"))
        new.flags[f"needs_review:{record.target}"] = True
        for promise in new.pending_promises.values():
            if record.target in promise.description:
                promise.needs_review = True
        new.events.append(
            new.touch(
                "override",
                "director",
                f"导演改写 {record.target}.{record.field}",
                before=before,
                after=record.after,
                reason=record.reason,
            )
        )
        return new, record

    def rollback(
        self, override_id: str, world: WorldState
    ) -> WorldState:
        """回到 override 记录中的 before 值（只回滚字段，不重放后续）"""
        record = next(
            (
                item for item in world.overrides
                if item.get("override_id") == override_id
            ),
            None,
        )
        if record is None:
            raise KeyError(f"未找到改写记录: {override_id}")
        new = world.model_copy(deep=True)
        self._write_field(
            new, record["target"], record["field"], record.get("before")
        )
        for item in new.overrides:
            if item.get("override_id") == override_id:
                item["rolled_back"] = True
        new.events.append(
            new.touch(
                "rollback",
                "director",
                f"回滚改写 {record['target']}.{record['field']}",
                override_id=override_id,
            )
        )
        return new

    # ---------------- 字段读写 ----------------

    @staticmethod
    def _read_field(world: WorldState, target: str, field: str) -> Any:
        if target in world.characters:
            return getattr(world.characters[target], field, None)
        if target in world.locations:
            return getattr(world.locations[target], field, None)
        if target in ("world", "世界"):
            return world.flags.get(field)
        return None

    @staticmethod
    def _write_field(
        world: WorldState, target: str, field: str, value: Any
    ) -> None:
        if target in world.characters:
            char = world.characters[target]
            if field in CharState.model_fields:
                setattr(char, field, value)
            return
        if target in world.locations:
            loc = world.locations[target]
            if field in LocationState.model_fields:
                setattr(loc, field, value)
            return
        if target in ("world", "世界"):
            world.flags[field] = value


class AuthorityController:
    """按模式选择策略，并负责模式切换 checkpoint"""

    def __init__(
        self,
        game: Optional[GameAuthority] = None,
        director: Optional[DirectorAuthority] = None,
    ):
        self.game = game or GameAuthority()
        self.director = director or DirectorAuthority()

    def policy_for(self, mode: str):
        return self.director if mode == "director" else self.game

    def switch_mode(
        self,
        world: WorldState,
        target_mode: str,
        checkpoint_fn=None,
        label: str = "",
    ) -> Tuple[WorldState, str]:
        """切换模式：先落 checkpoint，再更新模式与强制导演帧标记"""
        if target_mode not in ("game", "director"):
            raise ValueError(f"未知模式: {target_mode}")
        checkpoint_id = ""
        if checkpoint_fn is not None:
            checkpoint_id = checkpoint_fn(
                world, label or f"switch_to_{target_mode}"
            )
        new = world.model_copy(deep=True)
        new.mode = target_mode  # type: ignore[assignment]
        new.flags["force_director_frame"] = True
        new.flags["last_checkpoint_id"] = checkpoint_id
        new.events.append(
            new.touch(
                "mode_switch",
                "system",
                f"模式切换为 {target_mode}",
                checkpoint_id=checkpoint_id,
            )
        )
        return new, checkpoint_id


__all__ = [
    "AuthorityController",
    "AuthorityPolicy",
    "DirectorAuthority",
    "FactOverride",
    "GameAuthority",
]
