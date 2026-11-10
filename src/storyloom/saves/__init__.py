"""
旧存档层 — 兼容转发层。

SaveService / SaveRecord / SaveSummary / state_from_save 已合并进 memory/checkpoint.py，
这里只是简单 re-export 以保证旧 import 路径继续工作。
新代码请用 ``from storyloom.memory.checkpoint import SaveService`` 或直接用 CheckpointStore。
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
