from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class RiskAlertSkill(Skill):
    name = "risk_alert"
    description = "风险预警(I-06): 识别排他性条款、倾向性评分、不合理要求"
    category = "interpret"
    version = "1.0.0"
    triggers = ["风险预警", "排他性条款", "倾向性评分", "不合理要求"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        if not tender_text:
            return SkillResult(success=False, error="招标文件内容为空")

        messages = [
            {
                "role": "system",
                "content": """你是招标文件风险预警专家。识别招标文件中的潜在风险条款。

识别维度：
1. 排他性条款:
   - 指定品牌、型号或特定技术参数(非功能性需求)
   - 设置不合理的地域限制
   - 要求特定业绩或奖项(与项目无关)
   - 设置过高的资质门槛(超出项目实际需要)
   - 指定特定专利或专有技术

2. 倾向性评分:
   - 评分标准偏向特定供应商
   - 设置主观评分项且无明确标准
   - 评分权重分配不合理
   - 加分项与项目实际需求无关
   - 价格分权重过低(低于法定比例)

3. 不合理要求:
   - 投标时间过短(不足法定天数)
   - 保证金金额过高
   - 履约条件过于苛刻
   - 付款条件不合理
   - 技术参数存在歧视性

4. 合规性风险:
   - 与现行法律法规冲突的条款
   - 违反政府采购程序的规定
   - 限制中小企业参与的条款

返回JSON:
{
  "total_risks": 数量,
  "by_severity": {
    "critical": 数量,
    "high": 数量,
    "medium": 数量,
    "low": 数量
  },
  "risks": [
    {
      "category": "exclusionary/biased_scoring/unreasonable/compliance",
      "title": "风险标题",
      "content": "原文条款内容",
      "location": "在文件中的位置",
      "severity": "critical/high/medium/low",
      "analysis": "风险分析说明",
      "legal_basis": "法律依据(如适用)",
      "suggestion": "应对建议",
      "negotiation_points": "质疑/投诉要点"
    }
  ],
  "overall_risk_level": "critical/high/medium/low",
  "actionable_recommendations": ["可操作的建议列表"]
}""",
            },
            {
                "role": "user",
                "content": f"请分析以下招标文件中的风险条款：\n\n{tender_text[:8000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)

        critical = [r for r in result.get("risks", []) if r.get("severity") in ("critical", "high")]
        if critical:
            result["has_critical_risks"] = True

        return SkillResult(success=True, data=result)
