from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class QualificationCheckSkill(Skill):
    name = "qualification_check"
    description = "资质证书核查(废标预防1)"
    category = "check"
    version = "1.0.0"
    triggers = ["资质", "证书", "资质核查"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")
        bid_deadline = ctx.parameters.get("bid_deadline", "")

        messages = [
            {
                "role": "system",
                "content": """你是资质证书核查专家。对投标文件中的资质证书进行5项核查：

①有效期核查：证书有效期是否覆盖投标截止日
②名称一致性：证书名称是否与招标要求完全一致
③企业名称一致性：企业名称与营业执照/公章是否一致
④三证合一核查：三证合一/旧版分离证书是否匹配
⑤清晰度评估：证书扫描件是否清晰可辨

返回JSON:
{
  "checks": [
    {
      "check_type": "validity/name_match/company_match/three_in_one/clarity",
      "check_name": "检查项名称",
      "certificate_name": "证书名称",
      "required_by_tender": "招标要求",
      "found_in_bid": "投标文件中的内容",
      "status": "pass/fail/warning",
      "detail": "详细说明",
      "suggestion": "修改建议"
    }
  ],
  "summary": {"total": 5, "passed": 3, "failed": 1, "warning": 1},
  "risk_level": "high/medium/low",
  "disqualification_risk": true/false
}""",
            },
            {
                "role": "user",
                "content": f"招标文件资质要求：\n{tender_text[:4000]}\n\n投标文件资质信息：\n{bid_text[:4000]}\n\n投标截止日：{bid_deadline}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        return SkillResult(
            success=True,
            data=result,
            warnings=[f"资质核查: {result.get('summary', {}).get('failed', 0)}项不通过"],
        )
