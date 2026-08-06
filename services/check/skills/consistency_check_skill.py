from __future__ import annotations

import re

from core.skill_engine.base import Skill, SkillContext, SkillResult


class ConsistencyCheckSkill(Skill):
    name = "consistency_check"
    description = "跨章节一致性校验(废标预防核心)，含事实校验+逻辑谬误+术语规范"
    category = "check"
    version = "2.0.0"
    triggers = ["一致性", "交叉校验", "矛盾检测"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        bid_text = ctx.parameters.get("bid_text", "")
        tender_text = ctx.parameters.get("tender_text", "")
        project_facts = ctx.parameters.get("project_facts", {})

        if not bid_text:
            return SkillResult(success=False, error="投标文件内容为空")

        rule_issues = self._rule_based_check(bid_text, project_facts)

        llm_issues = await self._llm_deep_check(ctx, bid_text, tender_text, project_facts)

        all_issues = rule_issues + llm_issues

        critical_count = sum(1 for i in all_issues if i.get("severity") == "critical")
        major_count = sum(1 for i in all_issues if i.get("severity") == "major")

        if critical_count > 0:
            risk_level = "high"
        elif major_count >= 3:
            risk_level = "high"
        elif major_count > 0:
            risk_level = "medium"
        else:
            risk_level = "low"

        return SkillResult(
            success=True,
            data={
                "checks": all_issues,
                "summary": {
                    "total": len(all_issues),
                    "critical": critical_count,
                    "major": major_count,
                    "minor": sum(1 for i in all_issues if i.get("severity") == "minor"),
                    "rule_based": len(rule_issues),
                    "llm_based": len(llm_issues),
                },
                "risk_level": risk_level,
                "has_critical_issues": critical_count > 0,
            },
            warnings=[f"发现{critical_count}处严重不一致"] if critical_count > 0 else [],
        )

    def _rule_based_check(self, bid_text: str, project_facts: dict) -> list[dict]:
        issues = []

        if not project_facts:
            return issues

        entity_keys = {
            "project_name": "项目名称",
            "company_name": "公司名称",
            "bidder_name": "投标人名称",
            "purchaser_name": "采购人名称",
            "agency_name": "代理机构名称",
        }
        for fact_key, label in entity_keys.items():
            value = str(project_facts.get(fact_key, "")).strip()
            if not value or len(value) < 4:
                continue
            if value not in bid_text:
                issues.append({
                    "check_type": "entity_mismatch",
                    "check_name": f"实体名称一致性",
                    "location_a": f"项目事实({label})",
                    "value_a": value,
                    "location_b": "投标文件全文",
                    "value_b": "未找到",
                    "status": "inconsistent",
                    "severity": "major",
                    "suggestion": f"投标文件中未出现{label}'{value}'，请确认是否遗漏",
                })

        date_keys = {
            "service_period": "服务期限",
            "bid_deadline": "投标截止日",
            "delivery_date": "交付日期",
        }
        for fact_key, label in date_keys.items():
            value = str(project_facts.get(fact_key, "")).strip()
            if not value or len(value) < 4:
                continue
            if value not in bid_text:
                issues.append({
                    "check_type": "date_conflict",
                    "check_name": f"时间一致性",
                    "location_a": f"项目事实({label})",
                    "value_a": value,
                    "location_b": "投标文件全文",
                    "value_b": "未找到",
                    "status": "warning",
                    "severity": "minor",
                    "suggestion": f"投标文件中未体现{label}'{value}'",
                })

        budget = str(project_facts.get("budget_amount", "")).strip()
        if budget:
            digits = re.findall(r"[\d,.]+", budget)
            for digit in digits:
                if len(digit) >= 3 and digit not in bid_text:
                    issues.append({
                        "check_type": "number_conflict",
                        "check_name": "数值一致性",
                        "location_a": "项目事实(预算金额)",
                        "value_a": digit,
                        "location_b": "投标文件全文",
                        "value_b": "未找到",
                        "status": "warning",
                        "severity": "minor",
                        "suggestion": f"预算金额中的'{digit}'未在投标文件中出现",
                    })

        return issues

    async def _llm_deep_check(
        self, ctx: SkillContext, bid_text: str, tender_text: str, project_facts: dict
    ) -> list[dict]:
        facts_summary = ""
        if project_facts:
            facts_lines = []
            for k, v in project_facts.items():
                if v and str(v).strip():
                    facts_lines.append(f"- {k}: {v}")
            facts_summary = "\n".join(facts_lines[:20])

        system_content = """你是标书一致性校验专家。请进行以下深度检查：

①工期一致性：技术方案中的工期 vs 商务标中的工期 vs 投标函承诺的工期
②金额一致性：各处报价金额是否一致（投标函总价 vs 报价明细合计 vs 商务标汇总）
③人员一致性：项目经理/技术负责人在技术方案和人员简历中是否一致
④承诺一致性：质保期/响应时间/服务承诺在不同章节是否一致
⑤企业信息一致性：公司名称/地址/联系方式在各处是否一致
⑥逻辑谬误检查：前后矛盾、逻辑不一致、表述漏洞
⑦编造信息检测：是否存在可能编造的企业资质、案例、人员信息

返回JSON:
{
  "checks": [
    {
      "check_type": "duration/amount/personnel/commitment/company_info/logic_fallacy/fabrication",
      "check_name": "检查项名称",
      "location_a": "位置1描述",
      "value_a": "值1",
      "location_b": "位置2描述",
      "value_b": "值2",
      "status": "consistent/inconsistent/warning",
      "severity": "critical/major/minor",
      "suggestion": "修改建议"
    }
  ]
}"""

        user_parts = [f"投标文件内容：\n{bid_text[:5000]}"]
        if tender_text:
            user_parts.append(f"招标文件内容（参考）：\n{tender_text[:2000]}")
        if facts_summary:
            user_parts.append(f"项目已确认事实：\n{facts_summary[:1000]}")

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

        try:
            result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
            return result.get("checks", []) if isinstance(result, dict) else []
        except Exception:
            return []
