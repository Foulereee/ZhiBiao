from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from core.llm_gateway.gateway import LLMGateway


@dataclass
class AgentContext:
    agent_id: str
    agent_name: str
    project_id: str = ""
    db: Any = None
    llm: LLMGateway | None = None
    tool_registry: Any = None
    message_bus: Any = None
    agent_pool: Any = None
    circuit_breaker: Any = None
    parameters: dict = field(default_factory=dict)


@dataclass
class AgentMessage:
    sender: str
    receiver: str
    message_type: str
    content: Any
    correlation_id: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    success: bool
    data: Any = None
    error: str | None = None
    tokens_consumed: int = 0
    tool_calls_log: list[dict] = field(default_factory=list)
    thinking_process: list[str] = field(default_factory=list)


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    handler: Callable
    ctx_provider: Callable | None = None

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


@dataclass
class FunctionCall:
    name: str
    arguments: str


@dataclass
class ToolCallItem:
    id: str
    function_name: str
    arguments: str

    @property
    def function(self) -> FunctionCall:
        return FunctionCall(self.function_name, self.arguments)


@dataclass
class ToolCallResponse:
    content: str = ""
    tool_calls: list = field(default_factory=list)
    has_tool_calls: bool = False



