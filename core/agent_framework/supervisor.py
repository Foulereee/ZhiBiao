import asyncio
import re
from collections import OrderedDict

from core.agent_framework.agent import Agent
from core.agent_framework.types import AgentResult

def _step(agent: str, task: str, timeout: int, review: bool = False) -> dict:
    return {"agent": agent, "task": task, "timeout": timeout, "require_review": review}

PIPELINE_TEMPLATES = {
    "bid_generation": OrderedDict([
        ("interpret", _step("tender_interpret_agent", "解读招标文件，提取关键信息", 180)),
        ("outline",   _step("outline_agent",           "基于解读结果生成投标大纲", 120, True)),
        ("content",   _step("content_agent",           "根据大纲逐章节生成投标内容", 300)),
        ("check",     _step("compliance_check_agent",  "全面检查投标文件的合规性", 120)),
        ("format",    _step("format_agent",            "排版美化投标文件", 60)),
        ("export",    _step("export_agent",            "导出最终投标文件", 60)),
    ]),
    "bid_check": OrderedDict([
        ("check",        _step("compliance_check_agent", "全面合规检查", 120)),
        ("format_check", _step("format_agent",           "格式检查", 60)),
    ]),
    "full_analysis": OrderedDict([
        ("interpret", _step("tender_interpret_agent", "15维度深度解读招标文件", 180)),
        ("risk",      _step("tender_interpret_agent", "风险预警分析", 60)),
    ]),
}

ERROR_STRATEGY_RULES = [
    ("*",                "timeout",              "retry",  {"max_retries": 2, "backoff_s": 5}),
    ("check",            "critical",             "goto",   {"target": "content", "max_retries": 2}),
    ("check",            "*",                    "retry",  {"max_retries": 1}),
    ("*",                "rate_limit",           "retry",  {"max_retries": 3, "backoff_s": 10}),
    ("interpret",        "*",                    "retry",  {"max_retries": 1}),
    ("format|export",    "*",                    "skip",   {}),
    ("*",                "*",                    "llm",    {}),
]


class ErrorStrategyEngine:

    def __init__(self, rules: list | None = None):
        self.rules = rules or ERROR_STRATEGY_RULES
        self._compile_rules()

    def _compile_rules(self):
        self._compiled = []
        for step_pattern, err_pattern, action, params in self.rules:
            step_re_str = step_pattern.replace("*", ".*")
            err_re_str = err_pattern.replace("*", ".*")
            self._compiled.append({
                "step_re": re.compile(f"^({step_re_str})$"),
                "err_re": re.compile(err_re_str),  # 无锚点，子串匹配
                "action": action,
                "params": params,
            })

    def decide(self, step_id: str, error: str) -> tuple[str, dict]:
        for rule in self._compiled:
            if rule["step_re"].match(step_id) and rule["err_re"].search(error):
                return rule["action"], rule["params"]
        return "llm", {}


class SupervisorAgent(Agent):

    name = "supervisor"
    description = "主管Agent：模板化流程编排，异常时LLM决策"
    available_tools = ["delegate_to_agent", "ask_human"]

    async def run(self, task: str, **kwargs) -> AgentResult:
        pipeline_type = kwargs.get("pipeline_type", "bid_generation")

        template = PIPELINE_TEMPLATES.get(pipeline_type)
        if template:
            plan = list(template.items())
        else:
            plan = await self._llm_plan(task, kwargs.get("project_id", ""))

        self.strategy = ErrorStrategyEngine()

        results, step_log = await self._execute_plan(
            plan, kwargs.get("project_id", ""), pipeline_type
        )

        return AgentResult(success=True, data={
            "results": results, "step_log": step_log,
            "used_template": template is not None,
        })

    async def _execute_plan(self, plan: list, project_id: str, pipeline_type: str):
        """执行计划（含配置化策略的异常处理 + goto 回退机制）"""
        results = {}
        step_log = []
        retry_counts: dict[str, int] = {}
        goto_targets: dict[str, int] = {}

        step_index: dict[str, int] = {}
        for i, (sid, _) in enumerate(plan):
            step_index[sid] = i

        idx = 0
        while idx < len(plan):
            step_id, step_def = plan[idx]
            agent = self.ctx.agent_pool.get_or_create(step_def["agent"], project_id, self.ctx)
            step_done = False

            while not step_done:
                try:
                    result = await asyncio.wait_for(
                        agent.run(step_def["task"], project_id=project_id,
                                  previous_results=results),
                        timeout=step_def.get("timeout", 180),
                    )
                except asyncio.TimeoutError:
                    result = AgentResult(success=False, error="timeout")

                if result.success:
                    results[step_id] = result.data
                    step_log.append({"step": step_id, "status": "completed"})

                    # 步骤成功 → 保存检查点（支持断点续跑）
                    if self.ctx.checkpoint:
                        completed_steps = [sl["step"] for sl in step_log
                                           if sl["status"] == "completed"]
                        try:
                            await self.ctx.checkpoint.save(
                                project_id=project_id,
                                step_id=step_id,
                                pipeline_type=pipeline_type,
                                completed_steps=completed_steps,
                                step_results=results,
                                errors=[sl for sl in step_log if sl["status"] not in ("completed", "skipped")],
                                retry_counts=retry_counts,
                            )
                        except Exception:
                            pass  # 检查点保存失败不影响主流程

                    step_done = True
                    break

                action, params = self.strategy.decide(step_id, result.error or "unknown")
                retry_key = f"{step_id}_{action}"
                retry_counts[retry_key] = retry_counts.get(retry_key, 0) + 1
                max_r = params.get("max_retries", 1)

                if action == "retry" and retry_counts[retry_key] <= max_r:
                    backoff = params.get("backoff_s", 0)
                    if backoff:
                        await asyncio.sleep(backoff)
                    continue
                elif action == "goto":
                    target = params["target"]
                    goto_targets[target] = goto_targets.get(target, 0) + 1
                    if goto_targets[target] > 2:
                        step_log.append({"step": step_id, "status": "goto_limit_exceeded",
                                         "target": target, "error": result.error})
                        return results, step_log
                    results.pop(target, None)
                    step_log.append({"step": step_id, "status": f"goto_{target}"})
                    idx = step_index.get(target, idx)
                    step_done = True
                    break
                elif action == "skip":
                    step_log.append({"step": step_id, "status": "skipped"})
                    step_done = True
                    break
                elif action == "llm":
                    llm_decision = await self._llm_decide_failure(
                        step_id, result.error or "", pipeline_type
                    )
                    llm_action = llm_decision.get("action", "abort")
                    llm_retry_key = f"{step_id}_llm"
                    retry_counts[llm_retry_key] = retry_counts.get(llm_retry_key, 0) + 1

                    if llm_action == "retry" and retry_counts[llm_retry_key] <= 1:
                        continue
                    elif llm_action == "skip":
                        step_log.append({"step": step_id, "status": "skipped_by_llm"})
                        step_done = True
                        break
                    else:
                        step_log.append({"step": step_id, "status": "failed",
                                         "error": result.error})
                        return results, step_log
                else:
                    step_log.append({"step": step_id, "status": "failed"})
                    return results, step_log

            idx += 1

        return results, step_log

    async def _llm_plan(self, task: str, project_id: str) -> list:
        messages = [
            {"role": "system", "content": "你是投标业务流程主管。请为以下任务规划执行步骤，"
                                          "每个步骤必须包含：id(步骤ID)、agent(执行的Agent名)、"
                                          "task(任务描述)、timeout(超时秒数，默认180)、"
                                          "require_review(是否需要人工审核，默认false)。"},
            {"role": "user", "content": task},
        ]
        plan = await self.ctx.llm.collect_json(messages=messages, temperature=0.2)
        return [(s["id"], {
            "agent": s.get("agent", s.get("id", "")),
            "task": s.get("task", s.get("description", s.get("id", ""))),
            "timeout": s.get("timeout", 180),
            "require_review": s.get("require_review", False),
        }) for s in plan.get("steps", [])]

    async def _llm_decide_failure(self, step_id: str, error: str, pipeline_type: str) -> dict:
        messages = [
            {"role": "system", "content": "当前步骤失败，固定策略无法处理。请决定：abort(终止)/retry(重试)/skip(跳过)"},
            {"role": "user", "content": f"步骤: {step_id}, 错误: {error}, 流程: {pipeline_type}"},
        ]
        return await self.ctx.llm.collect_json(messages=messages, temperature=0.1)
