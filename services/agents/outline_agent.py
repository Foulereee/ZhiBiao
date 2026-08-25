from __future__ import annotations

import json
from typing import Any

from core.agent_framework.agent import Agent
from core.agent_framework.types import AgentResult, ToolCallItem


class OutlineAgent(Agent):
    name = "outline_agent"
    description = "大纲规划师：基于解读结果生成投标大纲，对齐评分项"
    system_prompt = """你是投标文件大纲规划师。你可以使用以下工具完成任务：
1. outline_generate - 生成投标文件大纲
2. score_alignment - 将章节与评分项对齐
3. structure_template - 获取标准结构模板
4. query_analysis_db - 查询数据库中的招标解读结果（优先使用，~5ms）
5. ask_interpret_agent - 向解读Agent提问（仅当DB查询无法满足时使用，~5-15s）

DB优先原则：
- 优先使用 query_analysis_db 获取评分矩阵和解读结果
- 只有当数据库中没有所需信息时，才使用 ask_interpret_agent 向解读Agent提问"""
    default_temperature: float = 0.4
    available_tools: list[str] = [
        "outline_generate", "score_alignment", "structure_template",
        "query_analysis_db", "ask_interpret_agent",
    ]

    async def run(self, task: str, **kwargs) -> AgentResult:
        project_id = kwargs.get("project_id", "")

        # 确定性前置步骤：通过 ToolRegistry 查DB获取解读结果
        if self.ctx.tool_registry:
            try:
                analysis_result = await self.ctx.tool_registry.execute(
                    ToolCallItem(id="pre_check", function_name="query_analysis_db",
                                 arguments=json.dumps({"fields": ["scoring", "risk_flags"]})),
                    agent_name=self.name,
                )
                if not isinstance(analysis_result, dict) or "error" not in analysis_result:
                    self._memory.add_message("system",
                        f"招标解读结果：{json.dumps(analysis_result, ensure_ascii=False)[:500]}")
            except Exception:
                pass

        # 从DB恢复记忆上下文
        if project_id and self.ctx.db:
            try:
                await self._memory.restore_from_db(project_id)
            except Exception:
                pass

        return await self.think_and_act(
            task,
            max_iterations=kwargs.get("max_iterations", 8),
        )