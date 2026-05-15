from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class ValidityCheckSkill(Skill):
    name = "validity_check"
    description = "投标有效期核查(废标预防6)"
    category = "check"
    version = "1.0.0"
    triggers = ["有效期", "投标有效期", "有效期核查"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        messages = [
            {
                "role": "system",
                "content": """你是投标有效期核查专家。核查以下内容：

①投标有效期：投标文件承诺的有效期是否≥招标要求天数
②保函有效期：保函有效期是否覆盖投标有效期+30天
③资质有效期：所有资质证书有效期是否覆盖投标截止日
④CA证书有效期：CA数字证书是否在有效期内

返回JSON:
{
  "checks": [
    {
      "check_type": "bid_validity/guarantee_period/qualification_expiry/ca_expiry",
      "check_name": "检查项名称",
      "required_period": "招标要求",
      "actual_period": "投标文件承诺",
      "status": "pass/fail/warning",
      "detail": "详细说明",
      "suggestion": "修改建议"
    }
  ],
  "summary": {"total": 0, "passed": 0, "failed": 0, "warning": 0},
  "risk_level": "high/medium/low",
  "has_critical_issues": true/false
}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{tender_text[:3000]}\n\n投标文件：\n{bid_text[:3000]}",
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
            warnings=[f"有效期核查: {len(failed)}项不通过"] if failed else [],
        )
