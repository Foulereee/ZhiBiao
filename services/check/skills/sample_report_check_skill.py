from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class SampleReportCheckSkill(Skill):
    name = "sample_report_check"
    description = "样品/检测报告核查(C-18): CMA/CNAS资质、检测项对应、有效期核查"
    category = "check"
    version = "1.0.0"
    triggers = ["样品核查", "检测报告", "CMA核查", "CNAS核查"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        if not tender_text or not bid_text:
            return SkillResult(success=False, error="招标文件和投标文件内容不能为空")

        messages = [
            {
                "role": "system",
                "content": """你是投标文件样品/检测报告核查专家。对投标文件中的样品和检测报告进行以下核查：

1. CMA/CNAS资质核查:
   - 检测机构是否具备CMA(检验检测机构资质认定)资质
   - 检测机构是否具备CNAS(中国合格评定国家认可委员会)认可
   - 资质证书是否在有效期内
   - 资质范围是否覆盖招标要求的检测项目

2. 检测项目对应性核查:
   - 招标文件要求的检测项目是否在检测报告中全部覆盖
   - 检测参数、检测方法是否符合招标文件要求的标准
   - 检测结果是否满足招标文件规定的技术指标

3. 有效期核查:
   - 检测报告是否在有效期内
   - 报告出具日期是否在招标文件规定的时间范围内
   - 样品送检时间与报告出具时间的合理性

返回JSON:
{
  "total_checks": 数量,
  "passed": 数量,
  "failed": 数量,
  "warning": 数量,
  "checks": [
    {
      "check_type": "qualification/item_correspondence/validity",
      "check_name": "检查项名称",
      "tender_requirement": "招标文件要求",
      "bid_content": "投标文件内容",
      "status": "pass/fail/warning",
      "detail": "详细说明",
      "suggestion": "修改建议(仅fail/warning时填写)"
    }
  ],
  "qualification_summary": {
    "cma_valid": true/false,
    "cnas_valid": true/false,
    "coverage_rate": "检测项目覆盖率"
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
