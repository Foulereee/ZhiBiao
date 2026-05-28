from __future__ import annotations

import json
from typing import Any

from core.agent_framework.agent import Agent
from core.agent_framework.types import AgentResult, ToolCallItem


class ContentAgent(Agent):
    name = "content_agent"
    description = "内容撰写师：根据大纲逐章节生成投标内容，按需配图"
    system_prompt = """你是投标文件内容撰写师。你可以使用以下工具完成任务：
1. chapter_generate - 逐章节生成投标内容
2. content_expand - 扩写/细化已有内容
3. image_generate - 生成配图（流程图、架构图等）
4. query_analysis_db - 查询解读结果（DB优先，~5ms）
5. query_outline_db - 查询大纲结构（DB优先，~5ms）
6. ask_outline_agent - 向大纲Agent确认结构疑问（仅DB无法满足时，~5-15s）

工作原则：
- 每个章节内容必须紧扣评分项要求
- 优先通过DB获取大纲和解读信息，减少Agent间通信开销
- 先生成文字内容，再根据需求决定是否配图"""
    default_temperature: float = 0.6
    available_tools: list[str] = [
        "chapter_generate", "content_expand", "image_generate",
        "query_analysis_db", "query_outline_db", "ask_outline_agent",
    ]

    async def run(self, task: str, **kwargs) -> AgentResult:
        project_id = kwargs.get("project_id", "")

        # DB恢复记忆上下文
        if project_id and self.ctx.db:
            try:
                await self._memory.restore_from_db(project_id)
            except Exception:
                pass

        return await self.think_and_act(
            task,
            max_iterations=kwargs.get("max_iterations", 15),
        )