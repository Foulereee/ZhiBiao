from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentMemory:
    """标书场景记忆管理：静态上下文 + 滑动窗口。

    双层设计：
    - 静态上下文 (static_context)：存储 DB 恢复的摘要信息，永不随窗口滑动丢失
    - 滑动窗口 (working_memory)：ReAct 循环的短期上下文，超过 window_size 自动丢弃
    """

    window_size: int = 10
    db: Any = None
    _working_memory: deque = field(default_factory=deque, init=False, repr=False)
    _static_context: list[dict] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self):
        self._working_memory = deque(maxlen=self.window_size)

    def add_message(self, role: str, content: str):
        """添加消息到滑动窗口（会随窗口满被丢弃）"""
        self._working_memory.append({"role": role, "content": content})

    def add_static_context(self, role: str, content: str):
        """添加静态上下文（永不丢弃，用于DB恢复的摘要信息）"""
        self._static_context.append({"role": role, "content": content})

    def add_exchange(self, user: str, assistant: str):
        """添加一次问答"""
        self._working_memory.append({"role": "user", "content": user})
        self._working_memory.append({"role": "assistant", "content": assistant})

    def get_context(self) -> list[dict]:
        """获取完整上下文：静态上下文 + 滑动窗口（静态上下文始终在前）"""
        return self._static_context + list(self._working_memory)

    async def restore_from_db(self, project_id: str):
        """从DB恢复静态上下文——不会被滑动窗口挤出。

        与滑动窗口的区别：静态上下文始终保留在消息列表头部，
        确保 Agent 在长 ReAct 循环中不会忘记已有状态。
        """
        if not self.db:
            return
        from sqlalchemy import select

        from services.models import Analysis, Chapter, Outline

        # 清空旧静态上下文（恢复时重建）
        self._static_context.clear()

        result = await self.db.execute(
            select(Analysis).where(Analysis.project_id == project_id)
        )
        analysis = result.scalar_one_or_none()
        if analysis and analysis.dimensions:
            self.add_static_context("system",
                f"已有解读结果，包含维度：{list(analysis.dimensions.keys())}")

        result = await self.db.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        outline = result.scalar_one_or_none()
        if outline and outline.tree:
            chapters = outline.tree if isinstance(outline.tree, list) else []
            self.add_static_context("system",
                f"已有大纲，共 {len(chapters)} 个章节")

        result = await self.db.execute(
            select(Chapter).where(Chapter.project_id == project_id)
        )
        chapters = result.scalars().all()
        if chapters:
            completed = [c for c in chapters if c.status == "generated"]
            self.add_static_context("system",
                f"已有 {len(completed)}/{len(chapters)} 个章节已生成")
