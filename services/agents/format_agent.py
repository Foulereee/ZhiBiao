from __future__ import annotations

from typing import Any

from core.agent_framework.agent import Agent
from core.agent_framework.types import AgentResult


class FormatAgent(Agent):
    name = "format_agent"
    description = "排版专家：文档格式化和排版美化"
    system_prompt = """你是投标文件排版专家。你可以使用以下工具完成任务：
1. docx_format - DOCX格式排版
2. pdf_export - PDF导出
3. revision_diff - 版本差异对比

排版原则：
- 严格按照招标文件格式要求执行
- 保持目录结构清晰，页码连续
- 表格、图片排版符合规范"""
    default_temperature: float = 0.1
    available_tools: list[str] = [
        "docx_format", "pdf_export", "revision_diff",
    ]

    async def run(self, task: str, **kwargs) -> AgentResult:
        # 排版任务确定性高，大部分直接调工具，不走ReAct也接受
        return await self.think_and_act(
            task,
            max_iterations=kwargs.get("max_iterations", 3),
        )