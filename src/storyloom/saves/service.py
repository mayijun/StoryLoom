"""
兼容层：SaveService / SaveRecord 等已迁至 ``storyloom.memory.checkpoint``。
这里 re-export 以保持旧 import 路径 ``from storyloom.saves.service import SaveService`` 不 break。

新代码请直接用 ::

    from storyloom.memory.checkpoint import SaveService, CheckpointStore, CheckpointRecord
"""

from storyloom.memory.checkpoint import (
    CheckpointRecord,
    CheckpointStore,
    CheckpointSummary,
    SaveRecord,
    SaveService,
    SaveSummary,
    state_from_checkpoint,
    state_from_save,
)

__all__ = [
    "CheckpointRecord",
    "CheckpointStore",
    "CheckpointSummary",
    "SaveRecord",
    "SaveService",
    "SaveSummary",
    "state_from_checkpoint",
    "state_from_save",
]
