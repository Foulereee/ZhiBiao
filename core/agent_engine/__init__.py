# 延迟导入：orchestrator 依赖 langgraph（可选依赖），不安装时不应阻塞其他模块
def __getattr__(name):
    if name == "AgentOrchestrator":
        from core.agent_engine.orchestrator import AgentOrchestrator
        return AgentOrchestrator
    if name == "GateKeeper":
        from core.agent_engine.gate_keeper import GateKeeper
        return GateKeeper
    if name == "PipelineState":
        from core.agent_engine.state import PipelineState
        return PipelineState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["AgentOrchestrator", "GateKeeper", "PipelineState"]
