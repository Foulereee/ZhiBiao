from core.agent_framework.agent import Agent
from core.agent_framework.types import AgentContext


class AgentRegistry:

    def __init__(self):
        self._classes: dict[str, type[Agent]] = {}
        self._configs: dict[str, dict] = {}

    def register(self, agent_class: type[Agent], default_config: dict | None = None):
        if not agent_class.name:
            raise ValueError(f"Agent类 {agent_class.__name__} 必须定义 name 属性")
        self._classes[agent_class.name] = agent_class
        self._configs[agent_class.name] = default_config or {}

    def create_instance(self, name: str, ctx: AgentContext | None = None) -> Agent:
        cls = self._classes.get(name)
        if not cls:
            raise ValueError(f"Agent '{name}' 未注册")
        if ctx is None:
            ctx = AgentContext(agent_id=f"{name}_test", agent_name=name)
        for tool_name in cls.available_tools:
            tool = ctx.tool_registry.get_global(tool_name)
            if tool and tool.ctx_provider:
                tool.ctx_provider(ctx)
        return cls(ctx)

    def list_all(self) -> list[dict]:
        return [
            {"name": name, "description": cls.description, "version": cls.version}
            for name, cls in self._classes.items()
        ]

    def has(self, name: str) -> bool:
        return name in self._classes
