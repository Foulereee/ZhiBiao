from __future__ import annotations

import asyncio
from typing import Any

from langgraph.graph import StateGraph, END

from core.agent_engine.state import PipelineState
from core.agent_engine.gate_keeper import GateKeeper
from core.skill_engine.base import Skill, SkillContext
from core.skill_engine.registry import SkillRegistry
from core.llm_gateway.gateway import LLMGateway


class AgentOrchestrator:
    def __init__(self, llm_gateway: LLMGateway, skill_registry: SkillRegistry, projects_root: str = "./projects"):
        self.llm = llm_gateway
        self.skills = skill_registry
        self.gate_keeper = GateKeeper(projects_root)

    def build_pipeline(self, dsl: dict) -> Any:
        graph = StateGraph(PipelineState)

        for node_def in dsl["nodes"]:
            skill_name = node_def.get("skill", "")
            if skill_name and self.skills.has(skill_name):
                skill_cls = self.skills.get(skill_name)
            else:
                skill_cls = None
            graph.add_node(
                node_def["id"],
                self._wrap_node(node_def["id"], skill_cls, node_def),
            )

        for edge_def in dsl.get("edges", []):
            if "condition" in edge_def:
                graph.add_conditional_edges(
                    edge_def["from"],
                    self._make_router(edge_def["condition"]),
                    edge_def["targets"],
                )
            else:
                graph.add_edge(edge_def["from"], edge_def["to"])

        entry = dsl.get("entry")
        if not entry:
            raise ValueError("DSL必须包含entry字段指定入口节点")
        graph.set_entry_point(entry)
        return graph.compile()

    async def run_rounds(self, project_id: str, rounds: list[list[dict]]) -> dict[str, Any]:
        all_results = {}
        for round_idx, round_skills in enumerate(rounds):
            tasks = []
            for skill_def in round_skills:
                skill_name = skill_def.get("skill", "")
                if not self.skills.has(skill_name):
                    continue
                skill_cls = self.skills.get(skill_name)
                ctx = SkillContext(
                    project_id=project_id,
                    db=None,
                    llm=self.llm,
                    parameters=skill_def.get("parameters", {}),
                )
                skill = skill_cls()
                timeout = skill_def.get("timeout", 120)
                tasks.append(self._run_with_timeout(skill, ctx, timeout))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                skill_name = round_skills[i].get("skill", f"unknown_{i}")
                if isinstance(result, Exception):
                    all_results[skill_name] = {"success": False, "error": str(result)}
                elif isinstance(result, dict):
                    all_results[skill_name] = result

        return all_results

    def _wrap_node(self, node_id: str, skill_cls: type[Skill] | None, node_def: dict):
        async def node_fn(state: PipelineState) -> dict:
            project_id = state.get("project_id", "")
            if not self.gate_keeper.is_passed(project_id, node_id) and node_def.get("require_gate", False):
                return {"errors": state.get("errors", []) + [f"闸门未通过: {node_id}"]}

            if skill_cls is None:
                return {"current_stage": node_id}

            ctx = SkillContext(
                project_id=project_id,
                db=None,
                llm=self.llm,
                parameters=node_def.get("parameters", {}),
            )
            skill = skill_cls()
            timeout = node_def.get("timeout", 120)
            try:
                result = await asyncio.wait_for(skill.safe_execute(ctx), timeout=timeout)
            except asyncio.TimeoutError:
                return {
                    "current_stage": node_id,
                    "errors": state.get("errors", []) + [f"节点超时: {node_id}"],
                }

            updates: dict[str, Any] = {"current_stage": node_id}
            if result.success:
                updates[f"stage_results.{node_id}"] = result.data
            else:
                updates["errors"] = state.get("errors", []) + [result.error or f"节点执行失败: {node_id}"]
            return updates

        return node_fn

    def _make_router(self, condition: dict):
        def router(state: PipelineState) -> str:
            operator = condition.get("operator", "has_errors")
            if operator == "has_errors":
                has_err = bool(state.get("errors", []))
                return condition["target_true"] if has_err else condition["target_false"]
            elif operator == "eq":
                actual = state.get(condition.get("field", ""))
                return condition["target_true"] if actual == condition.get("value") else condition["target_false"]
            elif operator == "gte":
                actual = state.get(condition.get("field", ""), 0)
                return condition["target_true"] if actual >= condition.get("value", 0) else condition["target_false"]
            return condition.get("target_false", END)

        return router

    async def _run_with_timeout(self, skill: Skill, ctx: SkillContext, timeout: int) -> dict:
        try:
            result = await asyncio.wait_for(skill.safe_execute(ctx), timeout=timeout)
            return {"success": result.success, "data": result.data, "error": result.error}
        except asyncio.TimeoutError:
            return {"success": False, "error": f"Skill {skill.name} 执行超时({timeout}s)"}
