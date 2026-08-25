from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class DisqualificationCheckSkill(Skill):
    name = "disqualification_check"
    description = "废标项检查(三轮AI:提取->逐项检查->补充定稿)"
    category = "check"
    version = "2.0.0"
    triggers = ["废标", "废标项"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")
        dq_clauses = ctx.parameters.get("disqualification_clauses", [])

        if not bid_text:
            return SkillResult(success=False, error="投标文件内容为空")

        if not dq_clauses:
            if not tender_text:
                return SkillResult(success=False, error="招标文件和废标条款均未提供")
            dq_clauses = await self._extract_clauses(ctx, tender_text)

        round2_items = await self._inspect_clauses(ctx, dq_clauses, bid_text)

        final_items = await self._finalize(ctx, dq_clauses, bid_text, round2_items)

        high_risk = [i for i in final_items if i.get("risk_level") == "high"]
        medium_risk = [i for i in final_items if i.get("risk_level") == "medium"]

        if high_risk:
            risk_level = "high"
        elif medium_risk:
            risk_level = "medium"
        else:
            risk_level = "low"

        return SkillResult(
            success=True,
            data={
                "total_clauses": len(final_items),
                "fully_responded": sum(1 for i in final_items if i.get("response_quality") == "明确"),
                "missing": sum(1 for i in final_items if not i.get("response_found")),
                "items": final_items,
                "risk_level": risk_level,
                "has_critical_issues": len(high_risk) > 0,
            },
            warnings=[f"发现{len(high_risk)}项高风险废标项"] if high_risk else [],
        )

    async def _extract_clauses(self, ctx: SkillContext, tender_text: str) -> list[dict]:
        messages = [
            {
                "role": "system",
                "content": """你是废标条款提取专家。从招标文件中提取所有可能导致废标或无效投标的条款。

区分两种类型：
- invalidBid: 投标无效条件（资格性审查不通过）
- rejectionItem: 废标项（符合性审查不通过）

返回JSON:
{"clauses": [{"id": "DQ-001", "type": "invalidBid/rejectionItem", "content": "废标条款内容", "severity": "critical/warning"}]}""",
            },
            {"role": "user", "content": f"招标文件：\n{tender_text[:6000]}"},
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        return result.get("clauses", []) if isinstance(result, dict) else []

    async def _inspect_clauses(
        self, ctx: SkillContext, clauses: list[dict], bid_text: str
    ) -> list[dict]:
        if not clauses:
            return []

        dq_text = "\n".join(
            f"- [{c.get('id', '')}] ({c.get('type', '')}) {c.get('content', '')}"
            for c in clauses
        )

        messages = [
            {
                "role": "system",
                "content": """你是废标风险检查专家。逐条检查投标文件是否完整响应了所有废标条款。

对每条废标条款：
1. 在投标文件中查找对应响应
2. 判断响应质量：明确/模糊/缺失
3. 评估风险等级

重要限制：
- 如果投标文件是图片/扫描件格式而你无法看到图片内容，不得判定"材料缺失"
- 只能基于你能看到的文本内容做判断

返回JSON:
{
  "items": [
    {
      "clause_id": "DQ-001",
      "clause_type": "invalidBid/rejectionItem",
      "clause_content": "废标条款内容",
      "response_found": true/false,
      "response_content": "找到的响应内容(原文摘录)",
      "response_quality": "明确/模糊/缺失",
      "risk_level": "high/medium/low",
      "suggestion": "修改建议"
    }
  ]
}""",
            },
            {
                "role": "user",
                "content": f"废标条款：\n{dq_text}\n\n投标文件：\n{bid_text[:6000]}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        return result.get("items", []) if isinstance(result, dict) else []

    async def _finalize(
        self, ctx: SkillContext, clauses: list[dict], bid_text: str, round2_items: list[dict]
    ) -> list[dict]:
        if not round2_items:
            return []

        existing_ids = {i.get("clause_id") for i in round2_items}
        missing_clauses = [c for c in clauses if c.get("id") not in existing_ids]

        items_summary = "\n".join(
            f"- {i.get('clause_id', '')}: response_found={i.get('response_found')}, "
            f"quality={i.get('response_quality')}, risk={i.get('risk_level')}"
            for i in round2_items
        )

        missing_text = ""
        if missing_clauses:
            missing_text = "\n\n未被检查的条款：\n" + "\n".join(
                f"- [{c.get('id', '')}] {c.get('content', '')}" for c in missing_clauses
            )

        messages = [
            {
                "role": "system",
                "content": """你是废标检查定稿专家。请对上一轮检查结果进行补充、去重和定稿：

1. 补充：检查是否有遗漏的废标条款未被检查
2. 去重：合并重复的检查项
3. 定稿：确认每项的风险等级和修改建议

返回JSON:
{
  "items": [
    {
      "clause_id": "DQ-001",
      "clause_type": "invalidBid/rejectionItem",
      "clause_content": "废标条款内容",
      "response_found": true/false,
      "response_content": "找到的响应内容",
      "response_quality": "明确/模糊/缺失",
      "risk_level": "high/medium/low",
      "suggestion": "修改建议"
    }
  ]
}""",
            },
            {
                "role": "user",
                "content": f"上一轮检查结果：\n{items_summary}{missing_text}\n\n投标文件（参考）：\n{bid_text[:3000]}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        return result.get("items", []) if isinstance(result, dict) else round2_items
