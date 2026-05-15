from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class ConsistencyCheckSkill(Skill):
    name = "consistency_check"
    description = "跨章节一致性校验(废标预防核心)"
    category = "check"
    version = "1.0.0"
    triggers = ["一致性", "交叉校验", "矛盾检测"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        bid_text = ctx.parameters.get("bid_text", "")

        if not bid_text:
            return SkillResult(success=False, error="投标文件内容为空")

        messages = [
            {
                "role": "system",
                "content": """你是标书一致性校验专家。检查投标文件中跨章节的数据是否自相矛盾：

①工期一致性：技术方案中的工期 vs 商务标中的工期 vs 投标函承诺的工期
②金额一致性：各处报价金额是否一致（投标函总价 vs 报价明细合计 vs 商务标汇总）
③人员一致性：项目经理/技术负责人在技术方案和人员简历中是否一致
④承诺一致性：质保期/响应时间/服务承诺在不同章节是否一致
⑤企业信息一致性：公司名称/地址/联系方式在各处是否一致

返回JSON:
{
  "checks": [
    {
      "check_type": "duration/amount/personnel/commitment/company_info",
      "check_name": "检查项名称",
      "location_a": "位置1描述",
      "value_a": "值1",
      "location_b": "位置2描述",
      "value_b": "值2",
      "status": "consistent/inconsistent/warning",
      "severity": "critical/major/minor",
      "suggestion": "修改建议"
    }
  ],
  "summary": {"total": 0, "consistent": 0, "inconsistent": 0, "warning": 0},
  "risk_level": "high/medium/low",
  "has_critical_issues": true/false
}""",
            },
            {
                "role": "user",
                "content": f"投标文件内容：\n{bid_text[:6000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        checks = result.get("checks", []) if isinstance(result, dict) else []
        inconsistent = [c for c in checks if c.get("status") == "inconsistent"]
        result.setdefault("has_critical_issues", len(inconsistent) > 0)
        result.setdefault("risk_level", "high" if inconsistent else "low")

        return SkillResult(
            success=True,
            data=result,
            warnings=[f"发现{len(inconsistent)}处不一致"] if inconsistent else [],
        )
