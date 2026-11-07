"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

存档服务：本地快照 + 回放。

M0 先落文件（data/saves/<project_id>/<save_id>.json），
后续接 DB 时保持 SaveRecord 契约不变即可。
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from storyloom.runtime.directive import StageScene
from storyloom.world.state import WorldState

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SaveRecord(BaseModel):
    """一次完整快照：状态 + 已渲染结果（回放不重新生成）"""

    save_id: str
    project_id: str
    label: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    turn: int = 0
    mode: str = "game"
    world_state: Dict[str, Any] = Field(default_factory=dict)
    directives: List[Dict[str, Any]] = Field(default_factory=list)
    text: str = ""
    memory_snapshot: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SaveSummary(BaseModel):
    save_id: str
    project_id: str
    label: str
    created_at: str
    turn: int
    mode: str


class SaveService:
    """文件型存档服务"""

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

    def _path(self, project_id: str, save_id: str) -> Path:
        return self._project_dir(project_id) / f"{save_id}.json"

    # ---------------- 写 ----------------

    def save(
        self,
        project_id: str,
        state: WorldState,
        scene: StageScene,
        label: str = "",
        memory_snapshot: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SaveRecord:
        save_id = f"save_{state.turn}_{uuid.uuid4().hex[:6]}"
        record = SaveRecord(
            save_id=save_id,
            project_id=project_id,
            label=label or f"第{state.turn}回合",
            turn=state.turn,
            mode=state.mode,
            world_state=state.model_dump(mode="json"),
            directives=[d.model_dump(mode="json") for d in scene.directives],
            text=scene.text,
            memory_snapshot=dict(memory_snapshot or {}),
            metadata=dict(metadata or {}),
        )
        directory = self._project_dir(project_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = self._path(project_id, save_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return record

    # ---------------- 读 ----------------

    def load(self, project_id: str, save_id: str) -> SaveRecord:
        path = self._path(project_id, save_id)
        if not path.exists():
            raise KeyError(f"存档不存在: {save_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SaveRecord.model_validate(raw)

    def list(self, project_id: str) -> List[SaveSummary]:
        directory = self._project_dir(project_id)
        if not directory.exists():
            return []
        summaries: List[SaveSummary] = []
        for path in directory.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                record = SaveRecord.model_validate(raw)
            except Exception:
                continue
            summaries.append(
                SaveSummary(
                    save_id=record.save_id,
                    project_id=record.project_id,
                    label=record.label,
                    created_at=record.created_at,
                    turn=record.turn,
                    mode=record.mode,
                )
            )
        summaries.sort(key=lambda s: s.created_at, reverse=True)
        return summaries

    def delete(self, project_id: str, save_id: str) -> bool:
        path = self._path(project_id, save_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def replay(self, project_id: str, save_id: str) -> SaveRecord:
        """回放：直接返回存档中的渲染结果，不重新生成"""
        return self.load(project_id, save_id)


def state_from_save(record: SaveRecord) -> WorldState:
    return WorldState.model_validate(record.world_state)


__all__ = ["SaveRecord", "SaveService", "SaveSummary", "state_from_save"]
