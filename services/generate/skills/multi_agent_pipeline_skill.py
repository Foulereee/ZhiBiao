from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

PIPELINE_STAGES = [
    {
        "id": "interpret",
        "name": "招标解读Agent",
        "description": "解读招标文件，提取关键信息",
        "skill": "tender_interpret",
        "gate": "interpret_review",
        "round": 1,
    },
    {
        "id": "outline",
        "name": "大纲生成Agent",
        "description": "根据解读结果生成投标大纲",
        "skill": "outline_gen",
        "gate": "outline_review",
        "round": 2,
    },
    {
        "id": "content",
        "name": "内容生成Agent",
        "description": "根据大纲逐章节生成内容",
        "skill": "content_gen",
        "gate": "content_review",
        "round": 3,
    },
    {
        "id": "check",
        "name": "质量检查Agent",
        "description": "对生成内容进行合规性和质量检查",
        "skill": "compliance_check",
        "gate": "check_review",
        "round": 4,
    },
    {
        "id": "format",
        "name": "格式排版Agent",
        "description": "对文档进行格式排版和美化",
        "skill": "docx_format",
        "gate": "format_review",
        "round": 5,
    },
    {
        "id": "final_check",
        "name": "终审Agent",
        "description": "最终全面检查，确保无遗漏",
        "skill": "full_check",
        "gate": "final_review",
        "round": 6,
    },
    {
        "id": "export",
        "name": "导出Agent",
        "description": "导出最终投标文件",
        "skill": "pdf_export",
        "gate": None,
        "round": 7,
    },
]


class MultiAgentPipelineSkill(Skill):
    name = "multi_agent_pipeline"
    description = "7-Agent标书生成流水线"
    category = "generate"
    version = "2.0.0"
    triggers = ["流水线", "多Agent", "全流程", "自动生成"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        project_id = ctx.parameters.get("project_id", "")
        start_stage = ctx.parameters.get("start_stage", "interpret")
        skip_gates = ctx.parameters.get("skip_gates", False)
        max_concurrent = ctx.parameters.get("max_concurrent", 3)

        if not project_id:
            return SkillResult(success=False, error="缺少project_id")

        stage_results = {}
        errors = []
        start_idx = 0

        for i, stage in enumerate(PIPELINE_STAGES):
            if stage["id"] == start_stage:
                start_idx = i
                break

        stages_to_run = PIPELINE_STAGES[start_idx:]

        rounds = {}
        for stage in stages_to_run:
            round_num = stage.get("round", 0)
            if round_num not in rounds:
                rounds[round_num] = []
            rounds[round_num].append(stage)

        sorted_rounds = sorted(rounds.keys())

        for round_num in sorted_rounds:
            round_stages = rounds[round_num]

            if len(round_stages) == 1:
                result = await self._execute_stage_with_gate(
                    round_stages[0], ctx, stage_results, skip_gates, project_id
                )
                stage_results[round_stages[0]["id"]] = result
                if not result.get("success", False) and not skip_gates:
                    errors.append({
                        "stage": round_stages[0]["id"],
                        "error": result.get("error", "Unknown error"),
                    })
                    break
            else:
                semaphore = asyncio.Semaphore(max_concurrent)

                async def _run_concurrent(stg):
                    async with semaphore:
                        return stg["id"], await self._execute_stage_with_gate(
                            stg, ctx, stage_results, skip_gates, project_id
                        )

                tasks = [_run_concurrent(stg) for stg in round_stages]
                round_results = await asyncio.gather(*tasks, return_exceptions=True)

                should_break = False
                for res in round_results:
                    if isinstance(res, Exception):
                        errors.append({"stage": "unknown", "error": str(res)})
                        should_break = True
                        continue
                    stage_id, result = res
                    stage_results[stage_id] = result
                    if not result.get("success", False) and not skip_gates:
                        errors.append({
                            "stage": stage_id,
                            "error": result.get("error", "Unknown error"),
                        })
                        should_break = True

                if should_break and not skip_gates:
                    break

        completed_stages = len(stage_results)
        total_stages = len(stages_to_run)
        progress = round(completed_stages / max(total_stages, 1) * 100, 1)

        return SkillResult(
            success=len(errors) == 0,
            data={
                "pipeline_id": f"pipeline_{project_id[:8]}",
                "progress": progress,
                "completed_stages": completed_stages,
                "total_stages": total_stages,
                "stage_results": stage_results,
                "errors": errors,
                "current_stage": list(stage_results.keys())[-1] if stage_results else None,
            },
        )

    async def _execute_stage_with_gate(
        self,
        stage: dict,
        ctx: SkillContext,
        prev_results: dict,
        skip_gates: bool,
        project_id: str,
    ) -> dict:
        gate_name = stage.get("gate")
        if gate_name and not skip_gates:
            gate_passed = self._check_filesystem_gate(project_id, stage["id"])
            if not gate_passed:
                return {
                    "success": False,
                    "error": f"闸门 {gate_name} 未通过，请先确认上一阶段结果",
                    "gate_blocked": True,
                    "gate_name": gate_name,
                }

        stage_result = await self._execute_stage(stage, ctx, prev_results)

        if stage_result.get("success", False):
            data = stage_result.get("data", {})
            if isinstance(data, dict):
                risk_level = data.get("risk_level", "low")
                has_critical = data.get("has_critical_issues", False)
                if (risk_level == "high" or has_critical) and not skip_gates:
                    stage_result["gate_blocked"] = True
                    stage_result["gate_reason"] = (
                        f"存在高风险问题(risk_level={risk_level})，需要人工审核"
                    )

        return stage_result

    def _check_filesystem_gate(self, project_id: str, stage_id: str) -> bool:
        try:
            from core.agent_engine.gate_keeper import GateKeeper

            keeper = GateKeeper()
            return keeper.is_passed(project_id, stage_id)
        except Exception:
            return True

    async def _execute_stage(
        self, stage: dict, ctx: SkillContext, prev_results: dict
    ) -> dict:
        from core.skill_engine.registry import SkillRegistry

        registry = SkillRegistry.instance()
        skill_name = stage["skill"]

        try:
            skill_class = registry.get(skill_name)
            if not skill_class:
                return {"success": False, "error": f"Skill未注册: {skill_name}"}

            skill = skill_class()
            stage_ctx = SkillContext(
                project_id=ctx.project_id,
                db=ctx.db,
                llm=ctx.llm,
                parameters=self._build_stage_params(stage, prev_results, ctx),
            )

            result = await skill.safe_execute(stage_ctx)
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "warnings": result.warnings,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _build_stage_params(
        self, stage: dict, prev_results: dict, ctx: SkillContext
    ) -> dict:
        base_params = {"project_id": ctx.project_id}

        if stage["id"] == "interpret":
            base_params["document_text"] = ctx.parameters.get("tender_text", "")

        elif stage["id"] == "outline":
            interpret_data = prev_results.get("interpret", {}).get("data", {})
            base_params["mode"] = "aligned"
            base_params["scoring_matrix"] = interpret_data.get("scoring_matrix", {})

        elif stage["id"] == "content":
            outline_data = prev_results.get("outline", {}).get("data", {})
            base_params["chapter_title"] = ctx.parameters.get("chapter_title", "")
            base_params["chapter_outline"] = json.dumps(
                outline_data.get("outline", {}), ensure_ascii=False
            )
            base_params["tender_context"] = ctx.parameters.get("tender_text", "")[:4000]
            interpret_data = prev_results.get("interpret", {}).get("data", {})
            base_params["mandatory_requirements"] = interpret_data.get(
                "mandatory_requirements", []
            )

        elif stage["id"] == "check":
            base_params["tender_text"] = ctx.parameters.get("tender_text", "")
            base_params["bid_text"] = ctx.parameters.get("bid_text", "")

        elif stage["id"] == "format":
            base_params["file_path"] = ctx.parameters.get("file_path", "")
            base_params["mode"] = "format"

        elif stage["id"] == "final_check":
            base_params["tender_text"] = ctx.parameters.get("tender_text", "")
            base_params["bid_text"] = ctx.parameters.get("bid_text", "")
            check_data = prev_results.get("check", {}).get("data", {})
            base_params["check_results"] = check_data

        elif stage["id"] == "export":
            format_data = prev_results.get("format", {}).get("data", {})
            base_params["input_path"] = format_data.get("output_path", ctx.parameters.get("file_path", ""))
            base_params["output_format"] = ctx.parameters.get("output_format", "pdf")

        return base_params
