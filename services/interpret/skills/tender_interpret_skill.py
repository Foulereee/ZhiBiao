from __future__ import annotations

import asyncio
import json

from core.skill_engine.base import Skill, SkillContext, SkillResult

DIMENSIONS = [
    {"id": "project_info", "name": "项目信息", "prompt": "提取项目名称、项目编号、采购方式、预算金额、采购人信息"},
    {"id": "buyer_info", "name": "甲方信息", "prompt": "提取采购单位名称、地址、联系人、联系方式、主管部门"},
    {"id": "qualification", "name": "资格要求", "prompt": "提取所有资格要求：资质等级、注册资金、业绩要求、人员要求、设备要求"},
    {"id": "technical", "name": "技术需求", "prompt": "提取技术参数、技术标准、服务要求、验收标准、★▲标记的强制性参数"},
    {"id": "scoring", "name": "评分细则", "prompt": "提取评分标准：商务分权重、技术分权重、价格分权重、每项评分细则"},
    {"id": "disqualification", "name": "废标红线", "prompt": "提取所有废标条款：实质性要求、强制性条件、不满足即废标的条款"},
    {"id": "deposit", "name": "保证金", "prompt": "提取保证金金额、缴纳形式、截止时间、退还条件"},
    {"id": "opening", "name": "开标要求", "prompt": "提取开标时间、开标地点、密封要求、递交方式"},
    {"id": "evaluation", "name": "评标办法", "prompt": "提取评标方法(综合评分法/最低评标价法)、评标委员会组成、评标流程"},
    {"id": "commercial", "name": "商务评分", "prompt": "提取商务评分项：企业资质分、业绩分、财务状况分、信誉分"},
    {"id": "contract", "name": "合同条款", "prompt": "提取付款方式、违约责任、质保期、验收标准、争议解决方式"},
    {"id": "risk", "name": "风险提示", "prompt": "识别排他性条款、倾向性评分、不合理要求、潜在风险点"},
    {"id": "competition", "name": "竞争态势", "prompt": "分析潜在竞争对手、市场格局、竞争优势点"},
    {"id": "timeline", "name": "时间节点", "prompt": "提取所有关键时间：公告日、答疑截止日、投标截止日、开标日、合同签订日"},
    {"id": "contacts", "name": "关键联系人", "prompt": "提取采购人联系人、代理机构联系人、技术联系人及联系方式"},
]


class TenderInterpretSkill(Skill):
    name = "tender_interpret"
    description = "15维度招标文件解读"
    category = "interpret"
    version = "1.0.0"
    triggers = ["解读", "招标解读", "分析招标文件"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        document_text = ctx.parameters.get("document_text", "")
        if not document_text:
            return SkillResult(success=False, error="文档内容为空")

        max_concurrent = ctx.parameters.get("max_concurrent", 5)
        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}
        total_tokens = 0

        async def interpret_dimension(dim: dict):
            nonlocal total_tokens
            async with semaphore:
                prompt = self._build_prompt(dim, document_text)
                messages = [
                    {"role": "system", "content": f"你是招标文件分析专家。提取{dim['name']}信息，返回JSON格式。"},
                    {"role": "user", "content": prompt},
                ]
                try:
                    result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
                    return dim["id"], result, 0
                except Exception as e:
                    return dim["id"], {"error": str(e)}, 0

        tasks = [interpret_dimension(dim) for dim in DIMENSIONS]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                results[f"error_{id(item)}"] = {"error": str(item)}
                continue
            dim_id, result, tokens = item
            total_tokens += tokens
            results[dim_id] = result

        return SkillResult(
            success=True,
            data={"dimensions": results},
            tokens_consumed=total_tokens,
        )

    def _build_prompt(self, dimension: dict, text: str) -> str:
        relevant_text = self._extract_relevant_text(dimension["id"], text)
        return f"""请从以下招标文件内容中{dimension["prompt"]}。

招标文件内容：
{relevant_text}

返回JSON格式结果，字段名使用英文。如果某项信息在文件中未提及，对应字段填null。"""

    def _extract_relevant_text(self, dim_id: str, text: str) -> str:
        keyword_map = {
            "deposit": ["保证金", "保函", "投标保证"],
            "timeline": ["截止", "开标", "公告", "时间", "日期"],
            "scoring": ["评分", "分值", "权重", "评标"],
            "disqualification": ["废标", "无效", "拒绝", "实质性"],
        }
        keywords = keyword_map.get(dim_id, [])
        if not keywords:
            return text[:6000]
        lines = text.split("\n")
        relevant = []
        seen = set()
        for i, line in enumerate(lines):
            if any(kw in line for kw in keywords):
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                for j in range(start, end):
                    if j not in seen:
                        relevant.append(lines[j])
                        seen.add(j)
        if relevant:
            return "\n".join(relevant)[:6000]
        return text[:6000]
