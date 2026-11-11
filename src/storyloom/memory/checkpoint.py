"""
Checkpoint（原 SaveService）：SessionState 快照 + 回放。

合并进 memory 包后，Checkpoint 与 LayeredMemory 共用持久化后端，
是 SessionState（WorldState + LayeredMemory + 渲染历史）的统一快照机制。
玩家手动存档、模式切换前自动 checkpoint、事实改写前快照，
都走这里的同一个 Checkpoint 模型。

M0 先落文件（data/saves/<project_id>/<save_id>.json），
后续接 DB 时保持 CheckpointRecord 契约不变即可。
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from storyloom.memory.state import StageScene, WorldState

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class CheckpointRecord(BaseModel):
    """一次完整快照：状态 + 已渲染结果（回放不重新生成）

    kind: story=玩家主动保存的故事存档；checkpoint=模式切换/改写前等系统检查点
    """

    # alias "save_id" 兼容旧存档文件和现有 API/测试
    model_config = {"populate_by_name": True}

    checkpoint_id: str = Field(alias="save_id")
    project_id: str
    label: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    turn: int = 0
    mode: str = "game"
    kind: str = "story"
    world_state: Dict[str, Any] = Field(default_factory=dict)
    directives: List[Dict[str, Any]] = Field(default_factory=list)
    text: str = ""
    choices: List[Dict[str, Any]] = Field(default_factory=list)
    memory_snapshot: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # 兼容旧字段名 save_id（现有测试 / API 代码用 record.save_id 访问）
    @property
    def save_id(self) -> str:
        return self.checkpoint_id


class CheckpointSummary(BaseModel):
    model_config = {"populate_by_name": True}

    checkpoint_id: str = Field(alias="save_id")
    project_id: str
    label: str
    created_at: str
    turn: int
    mode: str
    kind: str = "story"

    @property
    def save_id(self) -> str:
        return self.checkpoint_id


def _infer_kind(label: str) -> str:
    """兼容旧存档：模式切换 / 改写前快照属于系统检查点"""
    if label.startswith("switch_to_") or label.startswith("before_override_"):
        return "checkpoint"
    return "story"


class CheckpointStore:
    """Checkpoint 存储：文件型快照（后续可接 DB）"""

    def __init__(self, root: Optional[str] = None):
        self.root = Path(
            root or os.getenv("STORYLOOM_SAVE_DIR", "")
            or PROJECT_ROOT / "data" / "saves"
        )

    # ---------------- 路径 ----------------

    def _project_dir(self, project_id: str) -> Path:
        safe = "".join(
            ch for ch in project_id if ch.isalnum() or ch in "-_"
        ) or "default"
        return self.root / safe

    def _path(self, project_id: str, checkpoint_id: str) -> Path:
        return self._project_dir(project_id) / f"{checkpoint_id}.json"

    # ---------------- 写 ----------------

    def create(
        self,
        project_id: str,
        state: WorldState,
        scene: StageScene,
        label: str = "",
        memory_snapshot: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        kind: str = "story",
    ) -> CheckpointRecord:
        checkpoint_id = f"save_{state.turn}_{uuid.uuid4().hex[:6]}"
        record = CheckpointRecord(
            checkpoint_id=checkpoint_id,
            project_id=project_id,
            label=label or f"第{state.turn}回合",
            turn=state.turn,
            mode=state.mode,
            kind=kind,
            world_state=state.model_dump(mode="json"),
            directives=[d.model_dump(mode="json") for d in scene.directives],
            text=scene.text,
            choices=[dict(c) for c in scene.choices],
            memory_snapshot=dict(memory_snapshot or {}),
            metadata=dict(metadata or {}),
        )
        directory = self._project_dir(project_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = self._path(project_id, checkpoint_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return record

    # ---------------- 读 ----------------

    def load(self, project_id: str, checkpoint_id: str) -> CheckpointRecord:
        path = self._path(project_id, checkpoint_id)
        if not path.exists():
            raise KeyError(f"Checkpoint 不存在: {checkpoint_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = CheckpointRecord.model_validate(raw)
        if "kind" not in raw:
            record.kind = _infer_kind(record.label)
        return record

    def list(self, project_id: str) -> List[CheckpointSummary]:
        directory = self._project_dir(project_id)
        if not directory.exists():
            return []
        summaries: List[CheckpointSummary] = []
        for path in directory.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                record = CheckpointRecord.model_validate(raw)
            except Exception:
                continue
            kind = record.kind if "kind" in raw else _infer_kind(record.label)
            summaries.append(
                CheckpointSummary(
                    checkpoint_id=record.checkpoint_id,
                    project_id=record.project_id,
                    label=record.label,
                    created_at=record.created_at,
                    turn=record.turn,
                    mode=record.mode,
                    kind=kind,
                )
            )
        summaries.sort(key=lambda s: s.created_at, reverse=True)
        return summaries

    def delete(self, project_id: str, checkpoint_id: str) -> bool:
        path = self._path(project_id, checkpoint_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def replay(self, project_id: str, checkpoint_id: str) -> CheckpointRecord:
        """回放：直接返回 checkpoint 中的渲染结果，不重新生成"""
        return self.load(project_id, checkpoint_id)

    # 兼容旧 API 名：save 是 create 的别名
    def save(self, *args, **kwargs) -> CheckpointRecord:
        return self.create(*args, **kwargs)


def state_from_checkpoint(record: CheckpointRecord) -> WorldState:
    return WorldState.model_validate(record.world_state)


# ============================================================
# 向后兼容别名（旧名 SaveService / SaveRecord / SaveSummary / state_from_save）
# 保留这些别名让现有代码不需要立刻改 import 路径。
# 下一阶段再统一替换所有引用。
# ============================================================

SaveRecord = CheckpointRecord
SaveSummary = CheckpointSummary
SaveService = CheckpointStore
state_from_save = state_from_checkpoint


__all__ = [
    "CheckpointRecord",
    "CheckpointSummary",
    "CheckpointStore",
    "state_from_checkpoint",
    # 兼容别名
    "SaveRecord",
    "SaveSummary",
    "SaveService",
    "state_from_save",
]
