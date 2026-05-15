from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class ComplianceCheckSkill(Skill):
    name = "compliance_check"
    description = "合规性检查"
    category = "check"
    version = "1.0.0"
    triggers = ["合规", "合规性", "硬性要求"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        if not tender_text or not bid_text:
            return SkillResult(success=False, error="招标文件和投标文件内容不能为空")

        messages = [
            {
                "role": "system",
                "content": """你是投标文件合规性检查专家。
逐条检查投标文件是否满足招标文件的所有硬性要求。

检查步骤：
1. 从招标文件提取所有硬性要求(必须/应当/须/不得/禁止)
2. 逐条在投标文件中查找对应响应
3. 判断每项是否满足

返回JSON:
{
  "total_requirements": 数量,
  "compliant": 数量,
  "non_compliant": 数量,
  "items": [
    {
      "requirement": "招标要求描述",
      "source_location": "招标文件位置",
      "response": "投标文件响应内容",
      "response_location": "投标文件位置",
      "status": "compliant/non_compliant/partial",
      "severity": "critical/major/minor",
      "suggestion": "修改建议"
    }
  ]
}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{tender_text[:6000]}\n\n投标文件：\n{bid_text[:6000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        non_compliant = [i for i in result.get("items", []) if i.get("status") in ("non_compliant", "partial")]
        if non_compliant:
            result["has_critical_issues"] = True

        return SkillResult(success=True, data=result)
