from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class PricingLogicCheckSkill(Skill):
    name = "pricing_logic_check"
    description = "报价逻辑闭环检查(C-23): 报价逻辑完整性、人天核验、费用分摊检查"
    category = "check"
    version = "1.0.0"
    triggers = ["报价逻辑", "人天核验", "费用分摊", "报价闭环"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        if not tender_text or not bid_text:
            return SkillResult(success=False, error="招标文件和投标文件内容不能为空")

        messages = [
            {
                "role": "system",
                "content": """你是报价逻辑闭环检查专家。对投标文件的报价逻辑进行全面闭环检查。

检查维度：
1. 报价逻辑完整性:
   - 报价总表与分项报价表是否一致(纵向汇总校验)
   - 各分项报价之和是否等于投标总价
   - 报价明细表与汇总表是否对应
   - 是否存在遗漏的报价项
   - 报价项目是否完整覆盖招标文件要求的全部费用项

2. 人天核验:
   - 人员投入总人天数与报价是否匹配
   - 各岗位人天单价×人天数=该岗位费用，验算是否正确
   - 人天单价是否在合理范围内(与市场价对比)
   - 人员配置数量与工作量是否匹配
   - 加班/差旅等人天计算是否合理

3. 费用分摊检查:
   - 直接费用与间接费用的分摊是否合理
   - 管理费/利润的计取基数和费率是否合理
   - 税金计算是否正确(税率、计税基数)
   - 各项费用占比是否在合理范围内
   - 是否存在重复计费的项目

返回JSON:
{
  "total_checks": 数量,
  "passed": 数量,
  "failed": 数量,
  "warning": 数量,
  "checks": [
    {
      "check_type": "completeness/person_day/cost_allocation",
      "check_name": "检查项名称",
      "expected": "预期值(数值或描述)",
      "actual": "实际值(数值或描述)",
      "deviation": "偏差(数值或描述)",
      "status": "pass/fail/warning",
      "detail": "详细说明",
      "suggestion": "修改建议"
    }
  ],
  "pricing_summary": {
    "total_price": 投标总价,
    "price_breakdown_consistent": true/false,
    "person_day_verified": true/false,
    "cost_allocation_reasonable": true/false,
    "arithmetic_errors": 算术错误数量
  },
  "risk_level": "high/medium/low"
}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{tender_text[:6000]}\n\n投标文件：\n{bid_text[:6000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)

        failed = [c for c in result.get("checks", []) if c.get("status") == "fail"]
        if failed:
            result["has_critical_issues"] = True

        return SkillResult(success=True, data=result)
