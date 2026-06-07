from __future__ import annotations

import json
from typing import Any

from core.agent_framework.agent import Agent
from core.agent_framework.types import AgentResult, ToolCallItem


class TenderInterpretAgent(Agent):
    name = "tender_interpret_agent"
    description = "招投标解读专家：提取招标文件关键信息、构建评分矩阵、识别风险"
    system_prompt = """你是招投标文件解读专家。你可以使用以下工具完成解读任务：
1. dimension_extract - 提取招标文件中的15个关键维度信息
2. scoring_matrix_build - 构建评分矩阵
3. risk_identify - 识别潜在风险点和废标条款
4. search_knowledge_base - 搜索知识库获取补充信息

工作流程：
- 先使用 dimension_extract 逐维度提取关键信息
- 然后使用 scoring_matrix_build 构建评分矩阵
- 最后使用 risk_identify 进行风险评估
- 遇到不确定的信息时，使用 search_knowledge_base 查询知识库"""
    default_temperature: float = 0.2
    available_tools: list[str] = [
        "dimension_extract",
        "scoring_matrix_build",
        "risk_identify",
        "search_knowledge_base",
    ]

    async def run(self, task: str, **kwargs) -> AgentResult:
        # 确定性前置步骤：查DB获取招标文件文本
        project_id = kwargs.get("project_id", "")

        if project_id and self.ctx.db:
            # 1. 通过 ToolRegistry 查询招标文件文本
            try:
                tool_call = ToolCallItem(
                    id="tender_preload",
                    function_name="query_analysis_db",
                    arguments=json.dumps({}),
                )
                result = await self.ctx.tool_registry.execute(
                    tool_call, agent_name=self.name,
                )
                if isinstance(result, dict) and "error" not in result:
                    self._memory.add_message(
                        "system",
                        f"已加载招标文件解读上下文：{json.dumps(result, ensure_ascii=False)}",
                    )
            except Exception:
                pass

            # 2. 从DB恢复记忆上下文（已有解读结果、大纲、章节）
            try:
                await self._memory.restore_from_db(project_id)
            except Exception:
                pass

        # 3. 进入 ReAct 循环
        return await self.think_and_act(
            task,
            max_iterations=kwargs.get("max_iterations", 10),
        )