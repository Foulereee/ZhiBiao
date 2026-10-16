from __future__ import annotations

import re

from core.skill_engine.base import Skill, SkillContext, SkillResult

# 招标文件里与"废标/无效投标"强相关的章节特征词。
_DQ_KEYWORDS = (
    "废标", "无效投标", "投标无效", "否决", "否决投标", "不予受理",
    "符合性审查", "资格性审查", "响应性", "资格审查", "资格要求", "投标人资格",
    "投标文件的组成", "投标文件应包括", "投标文件应包含", "投标文件的编制",
    "投标文件格式", "密封", "签字", "盖章", "★", "▲", "不满足", "不接受",
)

# 一次送进模型的最大字符数。原来直接 [:6000]，
# 实测招标文件 67510 字时模型只能看到 8.9%，"废标"首现于第 14909 字 —— 完全看不到。
_TENDER_BUDGET = 30000
_EVIDENCE_BUDGET = 24000


def _tender_scan_context(tender_text: str, budget: int = _TENDER_BUDGET) -> str:
    """抽取招标文件里与废标有关的全部段落（而不是只取前 6000 字）。

    做法：头部保留 4000 字（项目概况/资格要求），再全文扫描命中 _DQ_KEYWORDS
    的整段并附上。实测这样能把"废标"相关条款从 0 条提升到覆盖全文。
    """
    if not tender_text:
        return ""
    head = tender_text[:4000]
    picked: list[str] = []
    seen: set[str] = set()
    for para in re.split(r"\n{2,}", tender_text):
        p = para.strip()
        if len(p) < 20 or len(p) > 2000 or p in seen:
            continue
        if any(k in p for k in _DQ_KEYWORDS):
            picked.append(p)
            seen.add(p)
    if not picked:
        return tender_text[:budget]
    merged = head + "\n\n===== 废标/符合性审查相关条款摘录 =====\n\n" + "\n\n".join(picked)
    return merged[:budget]


def _bid_evidence(bid_text: str, clauses: list[dict], budget: int = _EVIDENCE_BUDGET) -> str:
    """按废标条款在投标文件里定位"最可能承载响应内容"的段落。

    原实现是 `bid_text[:6000]` —— 一份 7 万字的投标文件只让模型看到 8.6%，
    且看到的是封面和投标函，技术/服务/资质响应全在视野之外，于是检查结论
    大量出现"未找到响应"的假阳性。

    这里按条款内容与段落的中文二字组重合度打分，每条条款取最相关的若干段，
    再把候选段落按原文顺序拼起来（保持可读性），总量封顶 budget。
    """
    if not bid_text:
        return ""
    paras = [p.strip() for p in re.split(r"\n{2,}|\n(?=\s*\|)", bid_text)]
    paras = [p for p in paras if len(p) >= 20]
    if not paras:
        return bid_text[:budget]

    def bigrams(s: str) -> set[str]:
        s = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}

    para_grams = [bigrams(p) for p in paras]
    chosen: set[int] = set()
    for clause in clauses or []:
        text = f"{clause.get('content', '')} {clause.get('type', '')}"
        cg = bigrams(text)
        if not cg:
            continue
        scored = []
        for i, pg in enumerate(para_grams):
            if not pg:
                continue
            overlap = len(cg & pg)
            if overlap:
                # 归一化：长段落不该因为字数多就占便宜
                scored.append((overlap / (len(cg) ** 0.5), i))
        scored.sort(reverse=True)
        for _score, i in scored[:3]:
            chosen.add(i)

    if not chosen:
        # 一条都对不上（例如条款全是编号引用），退回"头 + 尾"两段，
        # 尾部的响应承诺/附录通常比中段更关键
        return (bid_text[:budget // 2] + "\n\n……（略）……\n\n" + bid_text[-budget // 2:])[:budget]

    out: list[str] = []
    used = 0
    for i in sorted(chosen):
        p = paras[i]
        if used + len(p) > budget:
            break
        out.append(p)
        used += len(p)
    return "\n\n".join(out) if out else bid_text[:budget]


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
            {"role": "user", "content": f"招标文件：\n{_tender_scan_context(tender_text)}"},
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
                "content": (
                    f"废标条款：\n{dq_text}\n\n"
                    f"投标文件（已按条款定位相关段落）：\n{_bid_evidence(bid_text, clauses)}"
                ),
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
