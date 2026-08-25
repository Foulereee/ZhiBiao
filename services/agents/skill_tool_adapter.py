"""Skill → ToolDef 适配器。

将现有的 Skill 类包装为 Agent 可调用的 ToolDef。
关键设计：Skill 需要 ctx.project_id / ctx.db / ctx.llm，
但 LLM Function Calling 不会传递这些参数。
因此使用 ctx_provider 模式从 AgentContext 注入上下文。
"""

from __future__ import annotations

from typing import Any

from core.skill_engine.base import Skill, SkillContext
from core.agent_framework.types import AgentContext, ToolDef


def wrap_skill_for_agent(
    skill_class: type[Skill],
    tool_name: str,
    description: str,
    param_schema: dict[str, Any],
) -> ToolDef:
    """将 Skill 类包装为 Agent 可调用的 ToolDef。

    Args:
        skill_class: Skill 类（不是实例）
        tool_name: 工具名称（对应 Function Calling 的 function.name）
        description: LLM 侧工具描述
        param_schema: OpenAI Function Calling 参数 schema
    """

    async def handler(**kwargs):
        """工具执行入口——由 ToolRegistry.execute() 调用。

        kwargs 是 LLM 传入的参数（如 tender_text/bid_text 等）。
        project_id/db/llm 从 handler 的 _agent_ctx 属性注入。
        """
        if not hasattr(handler, '_agent_ctx') or handler._agent_ctx is None:
            return {"error": "Agent上下文未初始化，请通过 ctx_provider 注入"}

        ctx: AgentContext = handler._agent_ctx

        # 分离 LLM 传入的参数和注入的上下文
        llm_params = dict(kwargs)  # LLM Function Calling 传入的参数

        # 构造 SkillContext（注入 project_id/db/llm）
        skill_ctx = SkillContext(
            project_id=ctx.project_id,
            db=ctx.db,
            llm=ctx.llm,
            parameters=llm_params,
        )

        skill = skill_class()
        result = await skill.safe_execute(skill_ctx)
        if result.success:
            return result.data
        return {"error": result.error, "warnings": result.warnings}

    def ctx_provider(ctx: AgentContext):
        """Agent 创建时将 AgentContext 注入 handler"""
        handler._agent_ctx = ctx

    return ToolDef(
        name=tool_name,
        description=description,
        parameters=param_schema,
        handler=handler,
        ctx_provider=ctx_provider,
    )