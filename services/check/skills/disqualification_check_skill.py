from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class DisqualificationCheckSkill(Skill):
    name = "disqualification_check"
    description = "废标项检查"
    category = "check"
    version = "1.0.0"
    triggers = ["废标", "废标项"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")
        dq_clauses = ctx.parameters.get("disqualification_clauses", [])

        if not dq_clauses:
            messages = [
                {
                    "role": "system",
                    "content": """你是废标条款提取专家。从招标文件中提取所有废标条款。
返回JSON: {"clauses": [{"id": "DQ-001", "content": "废标条款内容", "severity": "critical/warning"}]}""",
                },
                {"role": "user", "content": f"招标文件：\n{tender_text[:6000]}"},
            ]
            extract_result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
            dq_clauses = extract_result.get("clauses", [])

        dq_text = "\n".join(f"- [{c.get('id', '')}] {c.get('content', '')}" for c in dq_clauses)

        messages = [
            {
                "role": "system",
                "content": """你是废标风险检查专家。
逐条检查投标文件是否完整响应了所有废标条款。

返回JSON:
{
  "total_clauses": 数量,
  "fully_responded": 数量,
  "missing": 数量,
  "items": [
    {
      "clause_id": "DQ-001",
      "clause_content": "废标条款内容",
      "response_found": true/false,
      "response_content": "找到的响应内容",
      "response_quality": "明确/模糊/缺失",
      "risk_level": "high/medium/low",
      "suggestion": "修改建议"
    }
  ]
}""",
            },
            {
                "role": "user",
                "content": f"废标条款：\n{dq_text}\n\n投标文件：\n{bid_text[:6000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        high_risk = [i for i in result.get("items", []) if i.get("risk_level") == "high"]

        return SkillResult(
            success=True,
            data=result,
            warnings=[f"发现{len(high_risk)}项高风险废标项"] if high_risk else [],
        )
