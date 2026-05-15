from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class SignatureCheckSkill(Skill):
    name = "signature_check"
    description = "签字盖章核查(废标预防3)"
    category = "check"
    version = "1.0.0"
    triggers = ["签字", "盖章", "签章", "公章", "CA证书"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        messages = [
            {
                "role": "system",
                "content": """你是签字盖章核查专家。核查投标文件的签章完整性：

①法人签字：投标函是否有法定代表人签字/盖章
②授权委托书：授权委托书是否完整（委托人/被委托人签字+公章）
③公章：所有要求加盖公章的页面是否已盖章
④骑缝章：投标文件是否有骑缝章
⑤CA证书：电子投标的CA数字证书是否在有效期内
⑥密封要求：纸质投标的密封标识是否规范

返回JSON:
{
  "checks": [
    {
      "check_type": "legal_rep_sign/authorization/seal/page_seal/counterfoil/ca_cert/sealing",
      "check_name": "检查项名称",
      "required": "招标要求",
      "found": "投标文件中的内容",
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
                "content": f"招标文件签章要求：\n{tender_text[:3000]}\n\n投标文件签章信息：\n{bid_text[:3000]}",
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
            warnings=[f"签章核查: {len(failed)}项不通过"] if failed else [],
        )
