from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class CrossCheckSkill(Skill):
    name = "cross_check"
    description = "交叉比对(C-06): 投标文件与招标评分标准逐项比对"
    category = "check"
    version = "1.0.0"
    triggers = ["交叉比对", "逐项比对", "评分项对照"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        if not tender_text or not bid_text:
            return SkillResult(success=False, error="招标文件和投标文件内容不能为空")

        messages = [
            {
                "role": "system",
                "content": """你是投标文件交叉比对专家。逐项比对投标文件与招标文件的评分标准。

比对步骤：
1. 从招标文件中提取所有评分项(商务分、技术分、价格分等)
2. 对每个评分项，在投标文件中查找对应的响应内容
3. 判断每个评分项的响应状态

响应状态定义：
- answered: 投标文件中有完整、明确的响应内容
- partial: 投标文件中有部分响应，但不完整或不够明确
- missing: 投标文件中未找到对应响应内容

返回JSON:
{
  "total_items": 数量,
  "answered": 数量,
  "partial": 数量,
  "missing": 数量,
  "coverage_rate": "百分比字符串",
  "items": [
    {
      "seq": 序号,
      "category": "商务/技术/价格/其他",
      "scoring_item": "评分项名称",
      "score": 分值,
      "scoring_criteria": "评分标准描述",
      "response_status": "answered/partial/missing",
      "response_content": "投标文件中的响应内容摘要(missing时为null)",
      "response_location": "响应内容在投标文件中的位置",
      "gap_analysis": "差距分析(仅partial/missing时填写)",
      "suggestion": "补充建议"
    }
  ],
  "risk_assessment": {
    "missing_score": 因缺失项可能丢失的总分,
    "partial_score": 因不完整项可能丢失的预估分,
    "max_obtainable_score": 最多可获分数
  }
}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{tender_text[:6000]}\n\n投标文件：\n{bid_text[:6000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)

        missing_items = [i for i in result.get("items", []) if i.get("response_status") == "missing"]
        if missing_items:
            result["has_missing_items"] = True

        return SkillResult(success=True, data=result)
