from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class MandatoryReqCheckSkill(Skill):
    name = "mandatory_req_check"
    description = "实质性要求对照表(废标预防5)"
    category = "check"
    version = "1.0.0"
    triggers = ["实质性要求对照", "★参数对照", "强制性参数检查"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        if not tender_text or not bid_text:
            return SkillResult(success=False, error="招标文件和投标文件内容不能为空")

        messages = [
            {
                "role": "system",
                "content": """你是实质性要求对照专家。逐条检查投标文件对招标文件中★▲强制性参数的响应：

1. 提取所有★▲标记的强制性技术参数
2. 在投标文件中逐条查找对应响应
3. 判断每项是否满足、是否有负偏离、是否有模糊表述

返回JSON:
{
  "total_mandatory": 0,
  "fully_responded": 0,
  "negative_deviation": 0,
  "vague_response": 0,
  "items": [
    {
      "param_id": "MP-001",
      "requirement": "★强制性参数描述",
      "marker": "★/▲",
      "category": "技术/商务/资质",
      "response_found": true/false,
      "response_content": "投标文件中的响应内容",
      "response_quality": "明确响应/模糊表述/未响应/负偏离",
      "status": "compliant/non_compliant/partial/vague",
      "severity": "critical/major/minor",
      "suggestion": "修改建议"
    }
  ],
  "has_critical_issues": true/false,
  "risk_level": "high/medium/low"
}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{tender_text[:5000]}\n\n投标文件：\n{bid_text[:5000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        if isinstance(result, dict):
            items = result.get("items", [])
            critical = [i for i in items if i.get("severity") == "critical" and i.get("status") != "compliant"]
            result.setdefault("has_critical_issues", len(critical) > 0)
            result.setdefault("risk_level", "high" if critical else "low")

        return SkillResult(
            success=True,
            data=result if isinstance(result, dict) else {},
            warnings=[f"发现{len(critical)}项★▲参数未满足"] if isinstance(result, dict) and result.get("has_critical_issues") else [],
        )
