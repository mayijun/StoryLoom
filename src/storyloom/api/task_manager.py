"""长任务管理器：线程池执行 + 内存字典追踪 + 后台清理

单进程版（StoryLoom 目前单机 FastAPI）。
任务结果 TTL 由 TASK_TTL_SECONDS 控制，到期自动清理。
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, Awaitable, Callable, Dict, Optional

from pydantic import BaseModel, Field

#: 任务结果保留时长（秒）；超过则从内存字典中删除，避免长期泄漏
TASK_TTL_SECONDS = 600

#: 同时运行的长任务上限（避免 CrewAI 并发打爆 API）
MAX_CONCURRENT = 2


class TaskStatus(BaseModel):
    task_id: str
    """pending / running / done / failed"""
    status: str = "pending"
    progress: int = 0
    step: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class _Registry:
    """线程安全的任务注册表"""

    def __init__(self):
        self._data: Dict[str, TaskStatus] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT, thread_name_prefix="storyloom-task")

    # ---------- 内部 ----------
    def _touch(self, task_id: str):
        ts = time.time()
        rec = self._data.get(task_id)
        if rec is not None:
            rec.updated_at = ts

    # ---------- 公共 ----------
    @contextmanager
    def _entry(self, task_id: str):
        """生成器中安全写状态的上下文；供 runner 内部使用"""
        rec = self._data[task_id]
        try:
            yield rec
        finally:
            pass

    def submit(
        self,
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> str:
        """提交一个 async 任务，返回 task_id

        coro_factory 返回的协程 **已经** 是事件循环绑定的（由 submit_async 封装），
        或在同步环境下 submit_sync 使用普通 callable。
        """
        task_id = uuid.uuid4().hex
        with self._lock:
            self._data[task_id] = TaskStatus(task_id=task_id)

        # 在线程池中跑事件循环（FastAPI 主循环在主线程，另起 loop 不冲突）
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                rec = self._data.get(task_id)
                if rec is not None:
                    rec.status = "running"
                    self._touch(task_id)

                coro = coro_factory()
                result = loop.run_until_complete(coro)

                with self._lock:
                    rec = self._data.get(task_id)
                    if rec is not None:
                        rec.status = "done"
                        rec.progress = 100
                        rec.result = result if isinstance(result, dict) else {"data": result}
                        self._touch(task_id)
            except Exception as exc:  # noqa: BLE001 — 需要兜底所有错误
                with self._lock:
                    rec = self._data.get(task_id)
                    if rec is not None:
                        rec.status = "failed"
                        rec.error = f"{type(exc).__name__}: {exc}"
                        self._touch(task_id)
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        self._executor.submit(_run)
        return task_id

    def submit_sync(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """提交一个同步 callable（供非 async 上下文）"""
        task_id = uuid.uuid4().hex
        with self._lock:
            self._data[task_id] = TaskStatus(task_id=task_id)

        def _run():
            try:
                rec = self._data.get(task_id)
                if rec is not None:
                    rec.status = "running"
                    self._touch(task_id)

                result = fn(*args, **kwargs)

                with self._lock:
                    rec = self._data.get(task_id)
                    if rec is not None:
                        rec.status = "done"
                        rec.progress = 100
                        rec.result = result if isinstance(result, dict) else {"data": result}
                        self._touch(task_id)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    rec = self._data.get(task_id)
                    if rec is not None:
                        rec.status = "failed"
                        rec.error = f"{type(exc).__name__}: {exc}"
                        self._touch(task_id)

        self._executor.submit(_run)
        return task_id

    def get(self, task_id: str) -> Optional[TaskStatus]:
        with self._lock:
            rec = self._data.get(task_id)
            if rec is None or rec.status != "running":
                return rec
            # 自动爬升 progress：业务代码没显式上报时，根据运行时长
            # 从 2% 线性爬到 95%，最长 15 分钟。真实 step 文字由业务代码
            # 用 update_progress 手动覆盖。
            elapsed = time.time() - rec.created_at
            auto_progress = min(95, max(2, int(elapsed / (15 * 60) * 93) + 2))
            if auto_progress > rec.progress:
                # 返回副本，不污染原 dict（原 progress 只被业务更新）
                return TaskStatus(
                    **{**rec.model_dump(), "progress": auto_progress}
                )
            return rec

    def update_progress(
        self,
        task_id: str,
        progress: Optional[int] = None,
        step: Optional[str] = None,
    ) -> None:
        """任务内部调用：上报进度。进度上限 100（done 时由 Runner 自动写）"""
        with self._lock:
            rec = self._data.get(task_id)
            if rec is None:
                return
            if progress is not None:
                rec.progress = max(0, min(progress, 99))
            if step is not None:
                rec.step = step
            self._touch(task_id)

    def pop(self, task_id: str) -> Optional[TaskStatus]:
        with self._lock:
            return self._data.pop(task_id, None)

    def cleanup_expired(self, ttl: int = TASK_TTL_SECONDS) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            expired = [
                tid
                for tid, rec in self._data.items()
                if rec.status in ("done", "failed") and (now - rec.updated_at) > ttl
            ]
            for tid in expired:
                self._data.pop(tid, None)
                removed += 1
        return removed


# 单例；FastAPI lifespan 里调用 start_cleanup_loop()
_registry = _Registry()


def get_task_registry() -> _Registry:
    return _registry


def start_cleanup_loop(ttl: int = TASK_TTL_SECONDS, interval: int = 60) -> None:
    """启动后台清理线程；应用启动时调用一次即可"""

    def _loop():
        while True:
            time.sleep(interval)
            try:
                removed = _registry.cleanup_expired(ttl)
                if removed > 0:
                    import logging
                    logging.getLogger(__name__).info(
                        "cleanup %d expired generation tasks", removed
                    )
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_loop, name="storyloom-task-cleanup", daemon=True).start()
