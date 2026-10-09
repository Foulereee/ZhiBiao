import inspect
import json
from typing import Any

from core.agent_framework.types import AgentContext, ToolDef
from core.skill_engine.base import SkillContext


def _accepts_ctx(handler) -> bool:
    """handler 是否接受按调用点注入的 _ctx 参数（显式声明或 **kwargs）。"""
    try:
        params = inspect.signature(handler).parameters
    except (TypeError, ValueError):
        return True
    if "_ctx" in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


class ToolRegistry:

    def __init__(self):
        self._global_tools: dict[str, ToolDef] = {}
        self._agent_scopes: dict[str, set[str]] = {}
        # 按 agent 名隔离的上下文（键为 agent 名）。全局共享的 ToolDef.handler
        # 不再持有 ctx，避免后注册的 Agent 覆盖前一个 Agent 的上下文。
        self._agent_contexts: dict[str, AgentContext] = {}

    def register_global(self, tool: ToolDef):
        self._global_tools[tool.name] = tool

    def grant_tools(self, agent_name: str, tool_names: list[str]):
        self._agent_scopes[agent_name] = set(tool_names)

    def bind_agent_context(self, agent_name: str, ctx: AgentContext):
        """绑定某个 Agent 的上下文（键为 agent 名，调用时按名取出并传入工具）。

        取代旧的"把 ctx 写到共享 handler 属性上"的做法：同一个 ToolDef 会被
        多个 Agent 共用，共享属性会被后创建/后执行的 Agent 覆盖。
        """
        if agent_name:
            self._agent_contexts[agent_name] = ctx

    def list_schemas(self, agent_name: str | None = None) -> list[dict]:
        if agent_name and agent_name in self._agent_scopes:
            allowed = self._agent_scopes[agent_name]
            return [self._global_tools[n].to_openai_schema() for n in allowed if n in self._global_tools]
        return [t.to_openai_schema() for t in self._global_tools.values()]

    def get_global(self, tool_name: str) -> ToolDef | None:
        return self._global_tools.get(tool_name)

    async def execute(self, tool_call, agent_name: str | None = None,
                      ctx: AgentContext | None = None) -> Any:
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        if agent_name and agent_name in self._agent_scopes:
            if tool_name not in self._agent_scopes[agent_name]:
                return {"error": f"Agent {agent_name} 无权使用工具 {tool_name}"}

        tool = self._global_tools.get(tool_name)
        if not tool:
            return {"error": f"工具 {tool_name} 不存在"}

        # 上下文按调用点传入（键为 agent 名），一个 Agent 的 ctx 不会被另一个覆盖
        call_ctx = ctx if ctx is not None else self._agent_contexts.get(agent_name)
        if call_ctx is not None and _accepts_ctx(tool.handler):
            return await tool.handler(_ctx=call_ctx, **tool_args)
        return await tool.handler(**tool_args)

    def wrap_skill(self, skill_class: type, tool_name: str, description: str, param_schema: dict):
        async def handler(**kwargs):
            kwargs.pop("_ctx", None)  # 调用点注入的上下文不属于 Skill 参数
            skill = skill_class()
            ctx = SkillContext(
                project_id=kwargs.pop("project_id", ""),
                db=kwargs.pop("db", None),
                llm=kwargs.pop("llm", None),
                parameters=kwargs,
            )
            result = await skill.safe_execute(ctx)
            return result.data if result.success else {"error": result.error}

        self.register_global(ToolDef(
            name=tool_name, description=description,
            parameters=param_schema, handler=handler,
        ))
