"""异步任务管理器。

解决 LLM 长耗时任务（大纲生成、内容生成等）前端超时问题。
模式：POST 立即返回 task_id → 前端轮询 GET /task/{task_id} 获取结果。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AsyncTask:
    task_id: str
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    progress_message: str = ""
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict:
        elapsed = 0.0
        if self.started_at:
            end = self.completed_at or time.monotonic()
            elapsed = end - self.started_at
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "result": self.result,
            "error": self.error,
            "elapsed_seconds": round(elapsed, 1),
        }


class TaskManager:
    """全局异步任务管理器（单例）"""

    _instance: TaskManager | None = None

    def __init__(self):
        self._tasks: dict[str, AsyncTask] = {}
        self._cleanup_interval = 300  # 5分钟清理一次
        self._max_task_age = 3600     # 1小时后清理

    @classmethod
    def instance(cls) -> TaskManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def create_task(self, task_type: str) -> AsyncTask:
        task = AsyncTask(task_id=str(uuid.uuid4()), task_type=task_type)
        self._tasks[task.task_id] = task
        logger.info(f"[TaskManager] 创建任务 task_id={task.task_id}, type={task_type}")
        return task

    def get_task(self, task_id: str) -> AsyncTask | None:
        return self._tasks.get(task_id)

    async def submit(
        self,
        task_type: str,
        coro_fn: Callable[..., Coroutine],
        *args,
        **kwargs,
    ) -> AsyncTask:
        """提交异步任务并立即返回 task_id。

        Args:
            task_type: 任务类型（如 outline_gen, content_gen）
            coro_fn: 异步函数
            *args, **kwargs: 传给 coro_fn 的参数
        """
        task = self.create_task(task_type)

        async def _run():
            task.status = TaskStatus.RUNNING
            task.started_at = time.monotonic()
            try:
                result = await coro_fn(*args, **kwargs)
                task.result = result
                task.status = TaskStatus.COMPLETED
                task.progress = 1.0
                task.completed_at = time.monotonic()
                elapsed = task.completed_at - task.started_at
                logger.info(f"[TaskManager] 任务完成 task_id={task.task_id}, "
                            f"耗时={elapsed:.1f}s")
            except Exception as e:
                task.error = str(e)
                task.status = TaskStatus.FAILED
                task.completed_at = time.monotonic()
                logger.error(f"[TaskManager] 任务失败 task_id={task.task_id}, "
                             f"error={e}")

        asyncio.create_task(_run())
        return task

    def cleanup_old_tasks(self):
        """清理过期任务"""
        now = time.monotonic()
        expired = [
            tid for tid, t in self._tasks.items()
            if now - t.created_at > self._max_task_age
        ]
        for tid in expired:
            del self._tasks[tid]
        if expired:
            logger.info(f"[TaskManager] 清理了 {len(expired)} 个过期任务")
