from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class DepositCheckSkill(Skill):
    name = "deposit_check"
    description = "投标保证金核查(废标预防2)"
    category = "check"
    version = "1.0.0"
    triggers = ["保证金", "投标保证", "保函"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        if not tender_text:
            return SkillResult(success=False, error="招标文件内容为空")

        messages = [
            {
                "role": "system",
                "content": """你是投标保证金核查专家。从招标文件和投标文件中核查保证金4项内容：

①金额一致性：保证金金额是否与招标要求精确一致（精确到分）
②缴纳形式：是否按要求的缴纳形式（电汇/保函/支票等）缴纳
③到账时间：保证金是否在截止时间之前到账
④保函有效期：保函有效期是否覆盖投标有效期+30天

返回JSON:
{
  "checks": [
    {
      "check_type": "amount/form/timing/guarantee_period",
      "check_name": "检查项名称",
      "required": "招标要求",
      "actual": "投标文件中的内容",
      "status": "pass/fail/warning",
      "detail": "详细说明",
      "suggestion": "修改建议"
    }
  ],
  "summary": {"total": 4, "passed": 0, "failed": 0, "warning": 0},
  "risk_level": "high/medium/low",
  "has_critical_issues": true/false
}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{tender_text[:4000]}\n\n投标文件：\n{bid_text[:4000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        checks = result.get("checks", []) if isinstance(result, dict) else []
        failed = [c for c in checks if c.get("status") == "fail"]
        result.setdefault("has_critical_issues", len(failed) > 0)
        result.setdefault("risk_level", "high" if failed else "low")

        return SkillResult(
            success=True,
            data=result,
            warnings=[f"保证金核查: {len(failed)}项不通过"] if failed else [],
        )
