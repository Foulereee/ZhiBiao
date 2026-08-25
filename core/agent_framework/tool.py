import json
from typing import Any

from core.agent_framework.types import ToolDef
from core.skill_engine.base import SkillContext


class ToolRegistry:

    def __init__(self):
        self._global_tools: dict[str, ToolDef] = {}
        self._agent_scopes: dict[str, set[str]] = {}

    def register_global(self, tool: ToolDef):
        self._global_tools[tool.name] = tool

    def grant_tools(self, agent_name: str, tool_names: list[str]):
        self._agent_scopes[agent_name] = set(tool_names)

    def list_schemas(self, agent_name: str | None = None) -> list[dict]:
        if agent_name and agent_name in self._agent_scopes:
            allowed = self._agent_scopes[agent_name]
            return [self._global_tools[n].to_openai_schema() for n in allowed if n in self._global_tools]
        return [t.to_openai_schema() for t in self._global_tools.values()]

    def get_global(self, tool_name: str) -> ToolDef | None:
        return self._global_tools.get(tool_name)

    async def execute(self, tool_call, agent_name: str | None = None) -> Any:
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        if agent_name and agent_name in self._agent_scopes:
            if tool_name not in self._agent_scopes[agent_name]:
                return {"error": f"Agent {agent_name} 无权使用工具 {tool_name}"}

        tool = self._global_tools.get(tool_name)
        if not tool:
            return {"error": f"工具 {tool_name} 不存在"}

        return await tool.handler(**tool_args)

    def wrap_skill(self, skill_class: type, tool_name: str, description: str, param_schema: dict):
        async def handler(**kwargs):
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
