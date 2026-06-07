from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.agent_framework.types import AgentContext
from core.agent_framework.supervisor import SupervisorAgent
from core.agent_framework.pool import AgentPool
from core.agent_framework.message_bus import MessageBus
from core.agent_framework.checkpoint import CheckpointManager
from core.agent_framework.tool import ToolRegistry
from core.llm_gateway.gateway import LLMGateway
from services.agents.agent_bootstrap import (
    create_agent_registry,
    register_all_tools,
)
from services.database import get_db


router = APIRouter(prefix="/agent", tags=["agent"])


class RunPipelineRequest(BaseModel):
    project_id: str
    pipeline_type: str = "bid_generation"
    params: dict[str, Any] = {}


class RunStepRequest(BaseModel):
    project_id: str
    agent_name: str
    task: str
    params: dict[str, Any] = {}


def _create_context(project_id: str, db: AsyncSession, llm: LLMGateway) -> AgentContext:
    """创建 AgentContext——每次请求都是新的"""
    return AgentContext(
        agent_id=str(uuid.uuid4()),
        agent_name="supervisor",
        project_id=project_id,
        db=db,
        llm=llm,
        parameters={},
    )


def _setup_tool_registry(ctx: AgentContext):
    """初始化工具注册表（Skill工具 + DB查询工具 + Agent通信工具）"""
    registry = ToolRegistry()
    register_all_tools(registry)
    ctx.tool_registry = registry


@router.post("/run")
async def run_pipeline(req: RunPipelineRequest, db: AsyncSession = Depends(get_db)):
    """启动完整的多Agent流程"""
    try:
        llm = LLMGateway()
        ctx = _create_context(req.project_id, db, llm)

        # 初始化注册表和工具
        agent_registry = create_agent_registry()
        _setup_tool_registry(ctx)

        # 初始化组件
        pool = AgentPool(agent_registry)
        bus = MessageBus()
        checkpoint = CheckpointManager()
        supervisor = SupervisorAgent(ctx)

        # 设置 context
        ctx.agent_pool = pool
        ctx.message_bus = bus
        ctx.checkpoint = checkpoint

        # 创建并注册 Agent 实例到 bus
        agent_names = [
            "tender_interpret_agent", "outline_agent", "content_agent",
            "compliance_check_agent", "format_agent", "export_agent",
        ]
        for name in agent_names:
            agent = pool.get_or_create(name, req.project_id, ctx)
            bus.register_agent(name, agent)

        # 执行流程
        result = await supervisor.run(
            task=f"执行{req.pipeline_type}流程，项目ID: {req.project_id}",
            project_id=req.project_id,
            pipeline_type=req.pipeline_type,
        )

        if not result.success:
            return {
                "success": False,
                "message": result.error or "流程执行失败",
                "data": result.data,
            }

        return {
            "success": True,
            "message": "流程执行完成",
            "data": result.data,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run_step")
async def run_step(req: RunStepRequest, db: AsyncSession = Depends(get_db)):
    """执行单个Agent步骤"""
    try:
        llm = LLMGateway()
        ctx = _create_context(req.project_id, db, llm)
        agent_registry = create_agent_registry()
        _setup_tool_registry(ctx)
        pool = AgentPool(agent_registry)
        ctx.agent_pool = pool

        agent = pool.get_or_create(req.agent_name, req.project_id, ctx)
        result = await agent.run(req.task, project_id=req.project_id, **req.params)

        return {
            "success": result.success,
            "message": result.error or "ok",
            "data": result.data,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{project_id}")
async def get_agent_status(project_id: str):
    """查询Agent执行状态"""
    try:
        checkpoint = CheckpointManager()
        data = await checkpoint.load_latest(project_id)
        if data is None:
            return {"success": True, "status": "not_started", "data": None}
        return {
            "success": True,
            "status": data.get("status", "unknown"),
            "completed_steps": data.get("completed_steps", []),
            "current_step": data.get("current_step", ""),
            "errors": data.get("errors", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume/{project_id}")
async def resume_pipeline(project_id: str, db: AsyncSession = Depends(get_db)):
    """从检查点恢复执行"""
    try:
        llm = LLMGateway()
        ctx = _create_context(project_id, db, llm)
        agent_registry = create_agent_registry()
        _setup_tool_registry(ctx)
        pool = AgentPool(agent_registry)
        bus = MessageBus()
        checkpoint = CheckpointManager()
        supervisor = SupervisorAgent(ctx)

        ctx.agent_pool = pool
        ctx.message_bus = bus
        ctx.checkpoint = checkpoint

        # 创建并注册 Agent 实例到 MessageBus（恢复流程同样需要）
        agent_names = [
            "tender_interpret_agent", "outline_agent", "content_agent",
            "compliance_check_agent", "format_agent", "export_agent",
        ]
        for name in agent_names:
            agent = pool.get_or_create(name, project_id, ctx)
            bus.register_agent(name, agent)

        result = await checkpoint.resume_from_checkpoint(
            project_id,
            lambda pid, cp: supervisor.run(
                task=f"恢复{cp.get('pipeline_type', 'bid_generation')}流程",
                project_id=pid,
                pipeline_type=cp.get("pipeline_type", "bid_generation"),
            ),
        )

        return {"success": result.success, "message": result.error or "ok", "data": result.data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))