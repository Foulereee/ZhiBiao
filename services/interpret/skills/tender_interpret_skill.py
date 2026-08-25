from __future__ import annotations

import asyncio
import re

from core.skill_engine.base import Skill, SkillContext, SkillResult

DIMENSIONS = [
    {
        "id": "project_info",
        "name": "项目信息",
        "prompt": "提取项目基本信息",
        "schema": {
            "project_name": "项目名称",
            "project_code": "项目编号/招标编号",
            "procurement_method": "采购方式（公开招标/竞争性谈判/询价/单一来源等）",
            "budget_amount": "预算金额（含单位）",
            "procurement_unit": "采购人/招标人名称",
            "project_overview": "项目概况简述",
        },
    },
    {
        "id": "buyer_info",
        "name": "甲方信息",
        "prompt": "提取采购单位详细信息",
        "schema": {
            "unit_name": "采购单位名称",
            "address": "单位地址",
            "contact_person": "联系人",
            "contact_phone": "联系电话",
            "supervisor_dept": "主管部门",
        },
    },
    {
        "id": "qualification",
        "name": "资格要求",
        "prompt": "提取投标人资格要求",
        "schema": {
            "qualification_level": "资质等级要求",
            "registered_capital": "注册资金要求",
            "performance_requirement": "业绩要求",
            "personnel_requirement": "人员要求（项目经理等）",
            "equipment_requirement": "设备要求",
            "other_requirements": "其他资格要求",
        },
    },
    {
        "id": "technical",
        "name": "技术需求",
        "prompt": "提取技术参数和标准",
        "schema": {
            "technical_parameters": "主要技术参数列表",
            "technical_standards": "技术标准/规范",
            "service_requirements": "服务要求",
            "acceptance_criteria": "验收标准",
            "mandatory_params": "★▲标记的强制性参数",
        },
    },
    {
        "id": "scoring",
        "name": "评分细则",
        "prompt": "提取评分标准和权重",
        "schema": {
            "evaluation_method": "评标方法（综合评分法/最低评标价法等）",
            "business_weight": "商务分权重",
            "technical_weight": "技术分权重",
            "price_weight": "价格分权重",
            "scoring_items": "各项评分细则列表（每项含name和description）",
        },
    },
    {
        "id": "disqualification",
        "name": "废标红线",
        "prompt": "提取废标条款和实质性要求",
        "schema": {
            "substantive_requirements": "实质性响应要求",
            "mandatory_conditions": "强制性条件",
            "disqualification_clauses": "废标条款列表（每项含description和clause_number）",
        },
    },
    {
        "id": "deposit",
        "name": "保证金",
        "prompt": "提取投标保证金信息",
        "schema": {
            "amount": "保证金金额",
            "payment_method": "缴纳形式（转账/保函等）",
            "deadline": "缴纳截止时间",
            "refund_conditions": "退还条件",
        },
    },
    {
        "id": "opening",
        "name": "开标要求",
        "prompt": "提取开标和投标递交信息",
        "schema": {
            "opening_time": "开标时间",
            "opening_location": "开标地点",
            "sealing_requirements": "密封要求",
            "submission_method": "递交方式",
            "submission_deadline": "投标截止时间",
        },
    },
    {
        "id": "evaluation",
        "name": "评标办法",
        "prompt": "提取评标方法和流程",
        "schema": {
            "method": "评标方法",
            "committee_composition": "评标委员会组成",
            "evaluation_process": "评标流程步骤列表",
        },
    },
    {
        "id": "commercial",
        "name": "商务评分",
        "prompt": "提取商务评分项",
        "schema": {
            "qualification_score": "企业资质评分",
            "performance_score": "业绩评分",
            "financial_score": "财务状况评分",
            "reputation_score": "信誉评分",
            "other_items": "其他商务评分项",
        },
    },
    {
        "id": "contract",
        "name": "合同条款",
        "prompt": "提取合同主要条款",
        "schema": {
            "payment_terms": "付款方式",
            "breach_liability": "违约责任",
            "warranty_period": "质保期",
            "acceptance_standard": "验收标准",
            "dispute_resolution": "争议解决方式",
        },
    },
    {
        "id": "risk",
        "name": "风险提示",
        "prompt": "识别招标文件中的风险点",
        "schema": {
            "exclusivity_clauses": "排他性条款",
            "biased_scoring": "倾向性评分",
            "unreasonable_requirements": "不合理要求",
            "potential_risks": "潜在风险列表（每项含description和type）",
        },
    },
    {
        "id": "competition",
        "name": "竞争态势",
        "prompt": "分析竞争态势",
        "schema": {
            "potential_competitors": "潜在竞争对手类型",
            "market_pattern": "市场格局分析",
            "competitive_advantages": "竞争优势点",
        },
    },
    {
        "id": "timeline",
        "name": "时间节点",
        "prompt": "提取所有关键时间节点",
        "schema": {
            "announcement_date": "公告日期",
            "clarification_deadline": "答疑/澄清截止日期",
            "bid_deadline": "投标截止日期",
            "opening_date": "开标日期",
            "contract_signing_date": "合同签订日期",
        },
    },
    {
        "id": "contacts",
        "name": "关键联系人",
        "prompt": "提取各方联系人信息",
        "schema": {
            "buyer_contact_person": "采购人联系人",
            "buyer_contact_info": "采购人联系方式",
            "agency_contact_person": "代理机构联系人",
            "agency_contact_info": "代理机构联系方式",
            "technical_contact_person": "技术联系人",
            "technical_contact_info": "技术联系方式",
        },
    },
]

_CAMEL_TO_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")

_DIMENSION_KEY_MAP: dict[str, dict[str, str]] = {}
for _dim in DIMENSIONS:
    _key_map: dict[str, str] = {}
    for _k in _dim["schema"]:
        _key_map[_k] = _k
        _snake = _CAMEL_TO_SNAKE_RE.sub("_", _k).lower()
        if _snake != _k:
            _key_map[_snake] = _k
        _key_map[_k.lower()] = _k
    _DIMENSION_KEY_MAP[_dim["id"]] = _key_map

_CHINESE_KEY_MAP: dict[str, dict[str, str]] = {
    "project_info": {
        "项目名称": "project_name", "项目编号": "project_code", "招标编号": "project_code",
        "采购方式": "procurement_method", "预算金额": "budget_amount",
        "采购人": "procurement_unit", "招标人": "procurement_unit",
        "采购人信息": "procurement_unit", "项目概况": "project_overview",
    },
    "buyer_info": {
        "单位名称": "unit_name", "采购单位名称": "unit_name", "地址": "address",
        "联系人": "contact_person", "联系电话": "contact_phone", "主管部门": "supervisor_dept",
        "procurementUnitName": "unit_name", "procurementUnitAddress": "address",
        "contactPerson": "contact_person", "contactInformation": "contact_phone",
        "principalDepartment": "supervisor_dept",
    },
    "qualification": {
        "资质等级": "qualification_level", "注册资金": "registered_capital",
        "业绩要求": "performance_requirement", "人员要求": "personnel_requirement",
        "设备要求": "equipment_requirement", "其他要求": "other_requirements",
        "项目经理": "personnel_requirement", "其他人员": "other_requirements",
    },
    "technical": {
        "技术参数": "technical_parameters", "技术标准": "technical_standards",
        "服务要求": "service_requirements", "验收标准": "acceptance_criteria",
        "强制性参数": "mandatory_params", "CA证书": "mandatory_params",
        "CA_certificate": "mandatory_params",
    },
    "scoring": {
        "评标方法": "evaluation_method", "商务分权重": "business_weight",
        "技术分权重": "technical_weight", "价格分权重": "price_weight",
        "评分细则": "scoring_items", "evaluation细则": "scoring_items",
        "business_weight": "business_weight", "technical_weight": "technical_weight",
        "price_weight": "price_weight",
    },
    "disqualification": {
        "实质性要求": "substantive_requirements", "强制性条件": "mandatory_conditions",
        "废标条款": "disqualification_clauses",
        "non_compliance_will_be_disqualified": "disqualification_clauses",
    },
    "deposit": {
        "金额": "amount", "缴纳形式": "payment_method", "截止时间": "deadline",
        "退还条件": "refund_conditions",
        "bidBondAmount": "amount", "bidBondPaymentForm": "payment_method",
        "bidBondDeadline": "deadline", "bidBondRefundConditions": "refund_conditions",
    },
    "opening": {
        "开标时间": "opening_time", "开标地点": "opening_location",
        "密封要求": "sealing_requirements", "递交方式": "submission_method",
        "投标截止时间": "submission_deadline",
        "bidOpeningTime": "opening_time", "bidOpeningLocation": "opening_location",
        "sealingRequirements": "sealing_requirements",
        "submissionMethod": "submission_method",
    },
    "evaluation": {
        "评标方法": "method", "委员会组成": "committee_composition",
        "评标流程": "evaluation_process",
        "评标委员会组成": "committee_composition",
    },
    "commercial": {
        "企业资质分": "qualification_score", "资质评分": "qualification_score",
        "业绩分": "performance_score", "业绩评分": "performance_score",
        "财务状况分": "financial_score", "财务评分": "financial_score",
        "信誉分": "reputation_score", "信誉评分": "reputation_score",
        "其他评分项": "other_items",
    },
    "contract": {
        "付款方式": "payment_terms", "违约责任": "breach_liability",
        "质保期": "warranty_period", "验收标准": "acceptance_standard",
        "争议解决方式": "dispute_resolution", "争议解决": "dispute_resolution",
    },
    "risk": {
        "排他性条款": "exclusivity_clauses", "倾向性评分": "biased_scoring",
        "不合理要求": "unreasonable_requirements", "潜在风险": "potential_risks",
    },
    "competition": {
        "潜在竞争对手": "potential_competitors", "市场格局": "market_pattern",
        "竞争优势": "competitive_advantages",
        "market_market_pattern": "market_pattern",
    },
    "timeline": {
        "公告日期": "announcement_date", "答疑截止": "clarification_deadline",
        "澄清截止": "clarification_deadline", "投标截止": "bid_deadline",
        "开标日期": "opening_date", "合同签订": "contract_signing_date",
        "answer疑问截止_date": "clarification_deadline",
    },
    "contacts": {
        "采购人联系人": "buyer_contact_person", "采购人联系方式": "buyer_contact_info",
        "代理机构联系人": "agency_contact_person", "代理机构联系方式": "agency_contact_info",
        "技术联系人": "technical_contact_person", "技术联系方式": "technical_contact_info",
        "procuring_entity_contact_person": "buyer_contact_person",
        "procuring_entity_contact_info": "buyer_contact_info",
    },
}


def _normalize_key(dim_id: str, key: str) -> str:
    key = key.strip().strip(":：")
    if not key:
        return key
    dim_key_map = _DIMENSION_KEY_MAP.get(dim_id, {})
    if key in dim_key_map:
        return dim_key_map[key]
    cn_map = _CHINESE_KEY_MAP.get(dim_id, {})
    if key in cn_map:
        return cn_map[key]
    snake = _CAMEL_TO_SNAKE_RE.sub("_", key).lower()
    if snake in dim_key_map:
        return dim_key_map[snake]
    if key.lower() in dim_key_map:
        return dim_key_map[key.lower()]
    return key


def _clean_value(value):
    if isinstance(value, str):
        value = re.sub(r"(.)\1{3,}", r"\1", value)
        value = re.sub(r"[zZ]{2,}", "", value)
        value = re.sub(r"D\d+D\d*", "", value)
        value = value.strip()
        if value and len(value) <= 1 and not value.isalnum():
            return None
    elif isinstance(value, dict):
        return {_normalize_key("", k): _clean_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_clean_value(item) for item in value]
    return value


def _normalize_dimension(dim_id: str, data: dict) -> dict:
    if not isinstance(data, dict) or "error" in data:
        return data
    schema_keys = set(DIMENSION_KEY_MAP.get(dim_id, {}).values()) if dim_id in {d["id"] for d in DIMENSIONS} else set()
    normalized = {}
    for key, value in data.items():
        clean_key = _normalize_key(dim_id, key)
        if schema_keys and clean_key not in schema_keys and key not in schema_keys:
            continue
        if isinstance(value, dict):
            normalized[clean_key] = _normalize_dimension(dim_id, value)
        elif isinstance(value, list):
            normalized[clean_key] = [
                {_normalize_key(dim_id, k): _clean_value(v) for k, v in item.items()}
                if isinstance(item, dict) else _clean_value(item)
                for item in value
            ]
        else:
            normalized[clean_key] = _clean_value(value)
    return normalized


DIMENSION_KEY_MAP = _DIMENSION_KEY_MAP


class TenderInterpretSkill(Skill):
    name = "tender_interpret"
    description = "15维度招标文件解读"
    category = "interpret"
    version = "3.0.0"
    triggers = ["解读", "招标解读", "分析招标文件"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        document_text = ctx.parameters.get("document_text", "")
        if not document_text:
            return SkillResult(success=False, error="文档内容为空")

        max_concurrent = ctx.parameters.get("max_concurrent", 3)
        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}

        async def interpret_dimension(dim: dict):
            async with semaphore:
                prompt = self._build_prompt(dim, document_text)
                schema_keys = list(dim["schema"].keys())
                schema_desc = "\n".join(
                    f'  "{k}": {v}' for k, v in dim["schema"].items()
                )
                example_json = "{\n" + ",\n".join(
                    f'  "{k}": null' for k in schema_keys
                ) + "\n}"
                messages = [
                    {
                        "role": "system",
                        "content": (
                            f"你是招标文件分析专家，专门提取{dim['name']}信息。\n"
                            "严格要求：\n"
                            f"1. 必须只返回以下{len(schema_keys)}个字段，字段名必须完全一致（英文snake_case）：\n"
                            + "\n".join(f'   - "{k}": {v}' for k, v in dim["schema"].items())
                            + "\n"
                            "2. 禁止使用中文作为字段名，禁止使用camelCase字段名\n"
                            "3. 字段值必须从招标文件原文中准确提取，不要编造或猜测\n"
                            "4. 如果文件中确实未提及某项信息，对应字段填null\n"
                            "5. 所有文本内容必须逐字准确复制，不要出现任何字符重复、乱码、截断\n"
                            "6. 不要添加任何Schema中未定义的额外字段\n"
                            f"\n返回格式示例：\n{example_json}"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]
                try:
                    result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
                    normalized = _normalize_dimension(dim["id"], result)
                    return dim["id"], normalized
                except Exception as e:
                    return dim["id"], {"error": str(e)}

        tasks = [interpret_dimension(dim) for dim in DIMENSIONS]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                continue
            dim_id, result = item
            results[dim_id] = result

        return SkillResult(
            success=True,
            data={"dimensions": results},
        )

    def _build_prompt(self, dimension: dict, text: str) -> str:
        relevant_text = self._extract_relevant_text(dimension["id"], text)
        schema_keys = list(dimension["schema"].keys())
        return (
            f"请从以下招标文件内容中{dimension['prompt']}。\n\n"
            f"必须只返回以下字段：{', '.join(schema_keys)}\n"
            f"字段名必须使用英文snake_case格式，禁止使用中文或camelCase。\n\n"
            f"招标文件内容：\n{relevant_text}\n\n"
            "重要提醒：\n"
            "- 逐字准确复制原文内容，不要出现任何字符重复或乱码\n"
            "- 未提及的字段填null\n"
            "- 不要添加额外字段"
        )

    def _extract_relevant_text(self, dim_id: str, text: str) -> str:
        keyword_map = {
            "project_info": ["项目", "招标", "采购", "预算", "编号", "公告"],
            "buyer_info": ["采购人", "招标人", "甲方", "联系人", "地址", "电话", "主管部门"],
            "qualification": ["资格", "资质", "注册资金", "业绩", "人员要求"],
            "technical": ["技术", "参数", "标准", "验收", "★", "▲", "强制性"],
            "deposit": ["保证金", "保函", "投标保证", "保证金额"],
            "timeline": ["截止", "开标", "公告", "时间", "日期", "日前"],
            "scoring": ["评分", "分值", "权重", "评标", "得分", "加分"],
            "disqualification": ["废标", "无效", "拒绝", "实质性", "否决"],
            "opening": ["开标", "递交", "密封", "投标截止"],
            "risk": ["排他", "倾向", "不合理", "风险", "限制"],
            "contract": ["付款", "违约", "质保", "验收标准", "争议"],
            "commercial": ["商务", "资质分", "业绩分", "财务", "信誉"],
            "evaluation": ["评标", "评审", "综合评分", "最低评标价"],
            "competition": ["竞争", "市场", "对手"],
            "contacts": ["联系人", "电话", "地址", "代理机构"],
        }
        keywords = keyword_map.get(dim_id, [])
        if not keywords:
            return text[:12000]

        lines = text.split("\n")
        relevant = []
        seen = set()
        for i, line in enumerate(lines):
            if any(kw in line for kw in keywords):
                start = max(0, i - 3)
                end = min(len(lines), i + 4)
                for j in range(start, end):
                    if j not in seen:
                        relevant.append(lines[j])
                        seen.add(j)

        result = "\n".join(relevant) if relevant else text[:12000]
        return result[:12000]
