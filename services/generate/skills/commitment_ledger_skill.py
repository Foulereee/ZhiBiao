from __future__ import annotations

"""全局口径台账（Commitment Ledger）。

解决的问题（实测 端头及超前支护技术研究与应用.docx，已被第三方复核确认）：
    同一份标书里 质保期 出现 12/24/36 个月三种说法、投标有效期 90/120/180 日历天三种、
    售后到场时间 2/4/8/24/48/72 小时六种、工作阻力从 280kN 到 42000kN 跨两个数量级。
    国内评标对"实质性内容前后不一致"通常按最不利于投标人的口径认定，甚至直接否决投标。

根因：正文是**逐章独立生成**的 —— 每章只拿到自己那一段大纲和 3000 字招标文件，
没有任何一处保存"全书统一的商务承诺"，模型每章都是重新"拍"一个数字。

做法：在批量生成正文**之前**跑一次本技能，从招标文件 + 解读结果里提炼出一份
"唯一口径表"，落库到 outline.tree["commitments"]，之后每一章的提示词都注入同一份表，
并明确要求"凡涉及以下事项，必须与口径表完全一致，不得出现第二种说法"。
"""

import logging

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

LEDGER_SYSTEM_PROMPT = """你是投标文件编制总负责人。请从招标文件中提炼出**全书必须统一**的关键口径。

要求：
1. 只提取招标文件明确规定的、或投标时必须做出承诺且全文必须一致的事项。
2. 每项给出**唯一**取值，不要给区间、不要给多个选项。
3. 招标文件没规定的项，填 "" 并在 note 里说明"招标文件未明确，由投标人统一承诺"。
4. 数值必须带单位，使用阿拉伯数字（如 "90日历天" 而不是 "九十日历天"）。
5. 不允许编造招标文件中不存在的数字。

返回 JSON：
{
  "items": [
    {"key": "warranty",      "label": "质保期",       "value": "自验收合格之日起24个月", "note": ""},
    {"key": "bid_validity",  "label": "投标有效期",   "value": "自投标截止之日起90日历天", "note": ""},
    {"key": "service_period","label": "服务期/工期",  "value": "合同签订后90日历天", "note": ""},
    {"key": "response_time", "label": "故障响应时限", "value": "接到通知后2小时内响应", "note": ""},
    {"key": "onsite_time",   "label": "故障到场时限", "value": "接到通知后24小时内到达现场", "note": ""},
    {"key": "payment",       "label": "付款方式",     "value": "", "note": ""},
    {"key": "acceptance",    "label": "验收标准",     "value": "", "note": ""},
    {"key": "pricing",       "label": "报价方式",     "value": "固定总价，含全部费用", "note": ""}
  ],
  "key_params": [
    {"item": "端头联排液压支架工作阻力", "required": "不低于3200kN"},
    {"item": "端头联排液压支架初撑力",   "required": "不低于2400kN"}
  ],
  "prohibited": ["不得出现有选择性的报价", "不得出现可调整价格的报价"]
}"""


class CommitmentLedgerSkill(Skill):
    name = "commitment_ledger"
    description = "全局口径台账:提炼全书必须统一的商务承诺与关键参数"
    category = "generate"
    version = "1.0.0"
    triggers = ["口径", "一致性", "承诺"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        analysis_digest = ctx.parameters.get("analysis_digest", "")

        if not tender_text and not analysis_digest:
            return SkillResult(success=False, error="招标文件与解读结果均为空")

        user_parts = []
        if analysis_digest:
            user_parts.append(f"【招标解读结果摘要】\n{analysis_digest[:6000]}")
        if tender_text:
            # 废标/符合性条款通常在后半部分，这里给足窗口
            user_parts.append(f"【招标文件正文】\n{tender_text[:20000]}")

        messages = [
            {"role": "system", "content": LEDGER_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

        try:
            result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        except Exception as e:  # pragma: no cover - 网络/模型异常
            logger.warning("[口径台账] 提炼失败: %s", e)
            return SkillResult(success=False, error=f"口径台账提炼失败: {e}")

        if not isinstance(result, dict):
            return SkillResult(success=False, error="口径台账返回格式异常")

        items = [i for i in (result.get("items") or []) if isinstance(i, dict) and i.get("label")]
        key_params = [p for p in (result.get("key_params") or []) if isinstance(p, dict) and p.get("item")]
        prohibited = [str(p) for p in (result.get("prohibited") or []) if str(p).strip()]

        if not items and not key_params:
            return SkillResult(success=False, error="口径台账为空")

        return SkillResult(
            success=True,
            data={
                "items": items,
                "key_params": key_params,
                "prohibited": prohibited,
            },
            warnings=[f"共提炼 {len(items)} 项商务口径、{len(key_params)} 项关键参数"],
        )