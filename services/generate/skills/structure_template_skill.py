from __future__ import annotations

import json
import logging
from typing import Any

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

BID_STRUCTURES = {
    "bid_letter": {
        "name": "投标函",
        "sections": [
            {"id": "bl_1", "title": "投标函", "level": 1, "page_target": 2,
             "content_hint": "致招标人，明确投标意向、投标总价、工期承诺、质量承诺"},
            {"id": "bl_2", "title": "投标函附录", "level": 1, "page_target": 1,
             "content_hint": "关键承诺事项汇总表"},
            {"id": "bl_3", "title": "法定代表人身份证明", "level": 1, "page_target": 1,
             "content_hint": "法定代表人姓名、职务、身份证号"},
            {"id": "bl_4", "title": "授权委托书", "level": 1, "page_target": 1,
             "content_hint": "委托代理人信息、授权范围、授权期限"},
            {"id": "bl_5", "title": "投标保证金交纳凭证", "level": 1, "page_target": 1,
             "content_hint": "保证金金额、缴纳形式、到账时间"},
            {"id": "bl_6", "title": "承诺书", "level": 1, "page_target": 1,
             "content_hint": "无行贿犯罪承诺、无重大违法承诺、履约承诺"},
        ],
    },
    "qualification": {
        "name": "资格审查",
        "sections": [
            {"id": "qa_1", "title": "营业执照", "level": 1, "page_target": 1,
             "content_hint": "三证合一/五证合一营业执照扫描件"},
            {"id": "qa_2", "title": "资质证书", "level": 1, "page_target": 2,
             "content_hint": "行业资质等级证书、安全生产许可证等"},
            {"id": "qa_3", "title": "财务状况", "level": 1, "page_target": 3,
             "content_hint": "近三年审计报告、资产负债表、利润表、现金流量表"},
            {"id": "qa_4", "title": "类似业绩", "level": 1, "page_target": 5,
             "content_hint": "近三年类似项目合同、验收证明、业主评价"},
            {"id": "qa_5", "title": "项目团队", "level": 1, "page_target": 3,
             "content_hint": "项目经理资质、技术负责人、关键岗位人员证书"},
            {"id": "qa_6", "title": "企业信誉", "level": 1, "page_target": 1,
             "content_hint": "信用中国截图、无不良记录证明"},
            {"id": "qa_7", "title": "社保及纳税证明", "level": 1, "page_target": 2,
             "content_hint": "近半年社保缴纳凭证、纳税证明"},
        ],
    },
    "technical": {
        "name": "技术标",
        "sections": [
            {"id": "ts_1", "title": "项目理解与背景分析", "level": 1, "page_target": 5,
             "content_hint": "项目背景理解、需求分析、痛点识别"},
            {"id": "ts_1_1", "title": "项目背景", "level": 2, "page_target": 2},
            {"id": "ts_1_2", "title": "需求分析", "level": 2, "page_target": 2},
            {"id": "ts_1_3", "title": "痛点与挑战", "level": 2, "page_target": 1},
            {"id": "ts_2", "title": "总体技术方案", "level": 1, "page_target": 8,
             "content_hint": "技术路线、架构设计、关键技术"},
            {"id": "ts_2_1", "title": "技术路线", "level": 2, "page_target": 2},
            {"id": "ts_2_2", "title": "系统架构设计", "level": 2, "page_target": 3},
            {"id": "ts_2_3", "title": "关键技术方案", "level": 2, "page_target": 3},
            {"id": "ts_3", "title": "实施方案", "level": 1, "page_target": 6,
             "content_hint": "实施计划、里程碑、资源配置"},
            {"id": "ts_3_1", "title": "实施计划与里程碑", "level": 2, "page_target": 2},
            {"id": "ts_3_2", "title": "团队组织与职责", "level": 2, "page_target": 2},
            {"id": "ts_3_3", "title": "资源配置方案", "level": 2, "page_target": 2},
            {"id": "ts_4", "title": "质量保障方案", "level": 1, "page_target": 4,
             "content_hint": "质量管理体系、质量控制措施、测试方案"},
            {"id": "ts_5", "title": "安全管理方案", "level": 1, "page_target": 3,
             "content_hint": "安全管理体系、安全措施、应急预案"},
            {"id": "ts_6", "title": "进度保障方案", "level": 1, "page_target": 3,
             "content_hint": "进度控制措施、风险应对、赶工预案"},
            {"id": "ts_7", "title": "售后服务方案", "level": 1, "page_target": 4,
             "content_hint": "服务承诺、响应时间、培训计划"},
        ],
    },
    "commercial": {
        "name": "商务标",
        "sections": [
            {"id": "cb_1", "title": "投标报价汇总表", "level": 1, "page_target": 2,
             "content_hint": "总报价、分项报价汇总"},
            {"id": "cb_2", "title": "分项报价明细表", "level": 1, "page_target": 5,
             "content_hint": "人工费、材料费、机械费、管理费、利润、税金"},
            {"id": "cb_3", "title": "报价编制说明", "level": 1, "page_target": 2,
             "content_hint": "编制依据、取费标准、价格来源"},
            {"id": "cb_4", "title": "成本分析", "level": 1, "page_target": 3,
             "content_hint": "直接成本、间接成本、风险成本分析"},
            {"id": "cb_5", "title": "价格优惠与让利", "level": 1, "page_target": 1,
             "content_hint": "优惠条件、让利幅度"},
        ],
    },
    "service": {
        "name": "售后服务",
        "sections": [
            {"id": "sv_1", "title": "售后服务承诺", "level": 1, "page_target": 2,
             "content_hint": "服务期限、服务范围、响应时间承诺"},
            {"id": "sv_2", "title": "服务团队", "level": 1, "page_target": 2,
             "content_hint": "售后服务人员配置、资质、联系方式"},
            {"id": "sv_3", "title": "培训方案", "level": 1, "page_target": 3,
             "content_hint": "培训计划、培训内容、培训方式"},
            {"id": "sv_4", "title": "应急预案", "level": 1, "page_target": 2,
             "content_hint": "故障等级划分、响应流程、备用方案"},
            {"id": "sv_5", "title": "质保方案", "level": 1, "page_target": 2,
             "content_hint": "质保期、质保范围、质保金"},
            {"id": "sv_6", "title": "备品备件方案", "level": 1, "page_target": 1,
             "content_hint": "备件清单、库存策略、供应周期"},
        ],
    },
}


class StructureTemplateSkill(Skill):
    name = "structure_template"
    description = "标书5大结构模板生成"
    category = "generate"
    version = "1.0.0"
    triggers = ["结构模板", "标书结构", "投标函", "技术标", "商务标"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        structure_type = ctx.parameters.get("structure_type", "all")
        tender_text = ctx.parameters.get("tender_text", "")

        if structure_type == "all":
            selected = BID_STRUCTURES
        elif structure_type in BID_STRUCTURES:
            selected = {structure_type: BID_STRUCTURES[structure_type]}
        elif "," in structure_type:
            selected = {}
            for part in structure_type.split(","):
                part = part.strip()
                if part in BID_STRUCTURES:
                    selected[part] = BID_STRUCTURES[part]
            if not selected:
                return SkillResult(success=False, error=f"未找到有效的结构类型: {structure_type}")
        else:
            return SkillResult(success=False, error=f"未知结构类型: {structure_type}")

        result_structures = {}
        for key, struct in selected.items():
            sections = struct["sections"]
            if tender_text and len(tender_text) > 100:
                try:
                    sections = await self._customize_with_tender(sections, tender_text, ctx)
                except Exception as e:
                    logger.warning(f"定制化结构失败，使用默认: {e}")

            result_structures[key] = {
                "name": struct["name"],
                "sections": sections,
                "total_pages": sum(s.get("page_target", 0) for s in sections),
                "total_sections": len(sections),
            }

        total_pages = sum(v["total_pages"] for v in result_structures.values())
        total_sections = sum(v["total_sections"] for v in result_structures.values())

        return SkillResult(
            success=True,
            data={
                "structures": result_structures,
                "total_pages": total_pages,
                "total_sections": total_sections,
                "available_types": list(BID_STRUCTURES.keys()),
            },
        )

    async def _customize_with_tender(
        self, sections: list[dict], tender_text: str, ctx: SkillContext
    ) -> list[dict]:
        section_titles = [s["title"] for s in sections]
        messages = [
            {
                "role": "system",
                "content": """你是标书结构优化专家。根据招标文件内容，调整标书结构模板：
1. 根据招标文件要求增删章节
2. 调整页数目标
3. 添加招标文件特别要求的章节

返回JSON格式的sections数组，每个元素包含id/title/level/page_target/content_hint字段。""",
            },
            {
                "role": "user",
                "content": f"默认结构: {json.dumps(section_titles, ensure_ascii=False)}\n\n招标文件(节选):\n{tender_text[:3000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.2)
        if result and isinstance(result, list):
            return result
        return sections


class ScoreCoverageSkill(Skill):
    name = "score_coverage"
    description = "评分矩阵覆盖率计算"
    category = "generate"
    version = "1.0.0"
    triggers = ["覆盖率", "评分覆盖", "评分矩阵"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        scoring_matrix = ctx.parameters.get("scoring_matrix", {})
        outline_sections = ctx.parameters.get("outline_sections", [])

        if not scoring_matrix:
            return SkillResult(success=False, error="无评分矩阵数据")

        score_items = self._extract_score_items(scoring_matrix)
        if not score_items:
            return SkillResult(success=False, error="评分矩阵中无评分项")

        coverage_map = {}
        covered_items = []
        uncovered_items = []

        for item in score_items:
            item_name = item.get("name", item.get("item", ""))
            item_score = item.get("score", item.get("weight", 0))
            matched_section = self._find_matching_section(item_name, outline_sections)

            if matched_section:
                covered_items.append({
                    "score_item": item_name,
                    "score": item_score,
                    "matched_section": matched_section,
                })
                coverage_map[item_name] = matched_section
            else:
                uncovered_items.append({
                    "score_item": item_name,
                    "score": item_score,
                    "suggestion": f"建议添加章节覆盖此项",
                })

        total_score = sum(item.get("score", 0) for item in score_items)
        covered_score = sum(item["score"] for item in covered_items)
        coverage_rate = round(covered_score / max(total_score, 1) * 100, 1)

        return SkillResult(
            success=True,
            data={
                "coverage_rate": coverage_rate,
                "total_items": len(score_items),
                "covered_items": len(covered_items),
                "uncovered_items": len(uncovered_items),
                "total_score": total_score,
                "covered_score": covered_score,
                "coverage_map": coverage_map,
                "covered_detail": covered_items,
                "uncovered_detail": uncovered_items,
            },
        )

    def _extract_score_items(self, matrix: dict) -> list[dict]:
        items = []
        if isinstance(matrix, list):
            return matrix

        for key, value in matrix.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        items.append(item)
                    elif isinstance(item, str):
                        items.append({"name": item, "score": 0})
            elif isinstance(value, dict):
                sub_items = self._extract_score_items(value)
                items.extend(sub_items)

        return items

    def _find_matching_section(self, score_item: str, sections: list) -> str:
        if not sections:
            return ""

        score_lower = score_item.lower()

        for section in sections:
            if isinstance(section, dict):
                title = section.get("title", "")
                if title and (title.lower() in score_lower or score_lower in title.lower()):
                    return title
                children = section.get("children", [])
                if children:
                    result = self._find_matching_section(score_item, children)
                    if result:
                        return result

        keywords = score_lower.split()
        for section in sections:
            if isinstance(section, dict):
                title = section.get("title", "").lower()
                if any(kw in title for kw in keywords if len(kw) >= 2):
                    return section.get("title", "")

        return ""
