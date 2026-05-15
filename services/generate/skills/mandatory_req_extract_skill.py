from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class MandatoryReqExtractSkill(Skill):
    name = "mandatory_req_extract"
    description = "实质性要求自动提取"
    category = "generate"
    version = "1.0.0"
    triggers = ["实质性要求", "强制性参数", "废标红线"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        document_text = ctx.parameters.get("document_text", "")
        if not document_text:
            return SkillResult(success=False, error="文档内容为空")

        messages = [
            {
                "role": "system",
                "content": """从招标文件中提取所有实质性要求和强制性条款。
包括：
1. 所有★▲标记的强制性技术参数
2. 废标红线条款(不满足即废标的条件)
3. 硬性资质要求
4. 评分细则(商务分/技术分/价格分权重)

返回JSON:
{
  "mandatory_params": [
    {"id": "MP-001", "content": "参数描述", "marker": "★/▲", "category": "技术/商务/资质"}
  ],
  "disqualification_clauses": [
    {"id": "DQ-001", "content": "废标条款描述", "severity": "critical/warning"}
  ],
  "hard_qualifications": [
    {"id": "HQ-001", "content": "资质要求描述", "type": "等级/注册资金/业绩"}
  ],
  "scoring_weights": {
    "commercial": 30,
    "technical": 50,
    "price": 20
  }
}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{document_text[:8000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        mandatory_count = len(result.get("mandatory_params", []))
        disqualification_count = len(result.get("disqualification_clauses", []))

        return SkillResult(
            success=True,
            data=result,
            warnings=[
                f"提取到{mandatory_count}项强制性参数",
                f"提取到{disqualification_count}条废标红线",
            ],
        )
