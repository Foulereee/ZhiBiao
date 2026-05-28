from __future__ import annotations

from typing import Any

from core.agent_framework.agent import Agent
from core.agent_framework.types import AgentResult


class ExportAgent(Agent):
    name = "export_agent"
    description = "导出专员：文件打包和多格式导出"
    system_prompt = """你是投标文件导出专员。你可以使用以下工具完成任务：
1. pdf_export - PDF导出
2. docx_export - DOCX导出
3. package_bundle - 打包所有文件

导出原则：
- 确保文件完整性和格式正确
- 按招标文件要求确定导出格式
- 打包时包含所有必要的附件和签章"""
    default_temperature: float = 0.1
    available_tools: list[str] = [
        "pdf_export", "docx_export", "package_bundle",
    ]

    async def run(self, task: str, **kwargs) -> AgentResult:
        return await self.think_and_act(
            task,
            max_iterations=kwargs.get("max_iterations", 3),
        )