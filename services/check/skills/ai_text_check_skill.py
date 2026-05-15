from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class AITextCheckSkill(Skill):
    name = "ai_text_check"
    description = "AI文本检查(C-07): 拼写/标点/实体识别"
    category = "check"
    version = "1.0.0"
    triggers = ["文本检查", "拼写检查", "标点检查", "错别字"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        bid_text = ctx.parameters.get("bid_text", "")
        if not bid_text:
            return SkillResult(success=False, error="投标文件内容为空")

        messages = [
            {
                "role": "system",
                "content": """你是投标文件文本质量检查专家。对投标文件进行以下三类检查：

1. 拼写检查(spelling): 错别字、同音字混淆、形近字错误
2. 标点检查(punctuation): 标点符号误用、中英文标点混用、缺失标点、多余标点
3. 实体识别(entity): 人名、公司名、项目名、日期、金额等关键实体是否前后一致、是否正确

检查要求：
- 逐段扫描文本，不遗漏任何问题
- 对每个问题给出准确位置描述
- 提供具体的修改建议

返回JSON:
{
  "total_issues": 数量,
  "by_type": {
    "spelling": 数量,
    "punctuation": 数量,
    "entity": 数量
  },
  "issues": [
    {
      "type": "spelling/punctuation/entity",
      "original": "原文内容",
      "location": "位置描述(如: 第3段第2行)",
      "description": "问题描述",
      "suggestion": "修改建议",
      "severity": "high/medium/low"
    }
  ],
  "overall_quality": "excellent/good/fair/poor"
}""",
            },
            {
                "role": "user",
                "content": f"请检查以下投标文件文本：\n\n{bid_text[:8000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)

        issues = result.get("issues", [])
        high_severity = [i for i in issues if i.get("severity") == "high"]
        if high_severity:
            result["has_critical_issues"] = True

        return SkillResult(success=True, data=result)
