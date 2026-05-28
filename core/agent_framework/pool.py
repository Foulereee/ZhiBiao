from collections import defaultdict

from core.agent_framework.agent import Agent
from core.agent_framework.memory import AgentMemory
from core.agent_framework.registry import AgentRegistry
from core.agent_framework.types import AgentContext


class AgentPool:

    def __init__(self, registry: AgentRegistry):
        self._registry = registry
        self._pools: dict[str, dict[str, Agent]] = defaultdict(dict)

    def get_or_create(self, agent_name: str, project_id: str,
                      parent_ctx: AgentContext | None = None) -> Agent:
        if agent_name in self._pools[project_id]:
            return self._pools[project_id][agent_name]

        if parent_ctx:
            agent_ctx = AgentContext(
                agent_id=f"{agent_name}_{project_id[:8]}",
                agent_name=agent_name,
                project_id=project_id,
                db=parent_ctx.db,
                llm=parent_ctx.llm,
                tool_registry=parent_ctx.tool_registry,
                message_bus=parent_ctx.message_bus,
                agent_pool=self,
                circuit_breaker=parent_ctx.circuit_breaker,
                parameters=parent_ctx.parameters,
            )
        else:
            agent_ctx = AgentContext(
                agent_id=f"{agent_name}_{project_id[:8]}",
                agent_name=agent_name,
                project_id=project_id,
            )
        agent = self._registry.create_instance(agent_name, agent_ctx)
        self._pools[project_id][agent_name] = agent
        return agent

    def get_project_agents(self, project_id: str) -> dict[str, Agent]:
        return self._pools.get(project_id, {})

    def destroy_project(self, project_id: str):
        if project_id in self._pools:
            del self._pools[project_id]

    def get_agent_memory(self, project_id: str, agent_name: str) -> AgentMemory | None:
        agent = self._pools.get(project_id, {}).get(agent_name)
        return agent._memory if agent else None
