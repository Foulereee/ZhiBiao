"""BidMaster 多Agent框架核心模块。

提供多Agent系统的核心组件：
- Agent 基类与ReAct循环
- ToolRegistry 工具注册与权限管理
- SupervisorAgent 流程编排（模板为主+LLM异常处理）
- MessageBus Agent间通信（DB优先原则）
- AgentPool Agent实例池化管理
- CheckpointManager 检查点管理（断点续跑）
- CircuitBreaker 熔断保护
- AgentMemory 滑动窗口记忆管理
"""

from core.agent_framework.agent import Agent
from core.agent_framework.registry import AgentRegistry
from core.agent_framework.tool import ToolRegistry
from core.agent_framework.supervisor import SupervisorAgent, ErrorStrategyEngine
from core.agent_framework.message_bus import MessageBus
from core.agent_framework.pool import AgentPool
from core.agent_framework.checkpoint import CheckpointManager
from core.agent_framework.circuit_breaker import CircuitBreaker
from core.agent_framework.memory import AgentMemory
from core.agent_framework.types import (
    AgentContext,
    AgentMessage,
    AgentResult,
    ToolDef,
    ToolCallItem,
    ToolCallResponse,
    FunctionCall,
)

__all__ = [
    "Agent",
    "AgentRegistry",
    "ToolRegistry",
    "SupervisorAgent",
    "ErrorStrategyEngine",
    "MessageBus",
    "AgentPool",
    "CheckpointManager",
    "CircuitBreaker",
    "AgentMemory",
    "AgentContext",
    "AgentMessage",
    "AgentResult",
    "ToolDef",
    "ToolCallItem",
    "ToolCallResponse",
    "FunctionCall",
]