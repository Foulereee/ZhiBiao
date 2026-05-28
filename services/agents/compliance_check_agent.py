from __future__ import annotations

import json
from typing import Any

from core.agent_framework.agent import Agent
from core.agent_framework.types import AgentResult, ToolCallItem


class ComplianceCheckAgent(Agent):
    name = "compliance_check_agent"
    description = "合规审查官：全面检查投标文件的合规性、一致性、强制性要求"
    system_prompt = """你是投标文件合规审查官。你可以使用以下工具完成任务：
1. compliance_check - 全面合规检查
2. mandatory_check - 强制性要求检查（资质、保证金等）
3. consistency_check - 一致性检查（前后矛盾、数据不一致）
4. query_analysis_db - 查询招标要求（DB优先，~5ms）
5. query_outline_db - 查询大纲结构（DB优先，~5ms）
6. query_chapter_db - 查询已生成的章节内容（DB优先，~5ms）
7. ask_interpret_agent - 向解读Agent确认招标要求细节（仅DB无法满足时）

检查原则：
- 严格对照招标文件中的评分标准和废标条款
- 优先通过DB获取信息，减少不必要的Agent间通信
- 列出所有不合规项，按严重程度排序（致命/警告/建议）"""
    default_temperature: float = 0.1
    available_tools: list[str] = [
        "compliance_check", "mandatory_check", "consistency_check",
        "query_analysis_db", "query_outline_db", "query_chapter_db",
        "ask_interpret_agent",
    ]

    async def run(self, task: str, **kwargs) -> AgentResult:
        project_id = kwargs.get("project_id", "")

        if project_id and self.ctx.db:
            try:
                await self._memory.restore_from_db(project_id)
            except Exception:
                pass

        return await self.think_and_act(
            task,
            max_iterations=kwargs.get("max_iterations", 10),
        )