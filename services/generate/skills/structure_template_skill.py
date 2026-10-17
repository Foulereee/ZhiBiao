from __future__ import annotations

import json
import logging
import re
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
        # 旧预设只有 5 个纯报价章节，而且"分项报价明细表"用的是施工计价口径
        # （人工费/材料费/机械费/管理费/利润/税金）—— 本平台做的是设备采购类
        # 项目，这套口径会直接把模型带偏，且缺了商务标真正必须有的一半内容。
        # 现按「商务标独立成册」的范围补齐：投标函与承诺、资格证明、
        # 财务与信用、业绩、商务条款响应与偏离、报价、付款与优惠。
        "sections": [
            {"id": "cb_1", "title": "投标函及投标承诺", "level": 1, "page_target": 2,
             "content_hint": "投标函、法定代表人授权、投标承诺与声明"},
            {"id": "cb_2", "title": "资格证明文件", "level": 1, "page_target": 3,
             "content_hint": "营业执照、资质证书、法定代表人身份证明、授权委托书"},
            {"id": "cb_3", "title": "财务与信用材料", "level": 1, "page_target": 3,
             "content_hint": "财务报表、审计报告、纳税与社保证明、信用证明"},
            {"id": "cb_4", "title": "业绩案例", "level": 1, "page_target": 3,
             "content_hint": "近三年同类项目业绩、合同及验收证明"},
            {"id": "cb_5", "title": "商务条款响应及偏离表", "level": 1, "page_target": 3,
             "content_hint": "逐条响应招标文件商务条款，列明响应对照与正负偏离"},
            {"id": "cb_6", "title": "投标报价汇总表", "level": 1, "page_target": 2,
             "content_hint": "投标总报价、分项报价汇总，金额一律使用待填占位符"},
            {"id": "cb_7", "title": "分项报价明细表", "level": 1, "page_target": 5,
             "content_hint": "按招标文件的工程量清单或设备清单逐项列示：名称、规格型号、"
                             "单位、数量、单价、合价；单价与合价写成 {{待填:单价}} 形式"},
            {"id": "cb_8", "title": "付款条件与优惠承诺", "level": 1, "page_target": 2,
             "content_hint": "付款方式响应、优惠条件、让利幅度、质保金约定"},
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


# ══════════════════════════════════════════════════════════════════════════
# 分值解析：招标解读给出的评分项往往只有名称 + 一段描述，
# 分值是写在描述里的（"2分/项，最高10分"），没有独立的 score 字段。
# 旧代码直接 item.get("score", 0) 取不到就是 0 —— 于是：
#   ① 送给大纲模型的评分矩阵里每一项都是 0 分；
#   ② 评分覆盖率算出来恒为 0%（分子分母都是 0）。
# 这里按"最高/满分/每项得分"从大到小取第一个能对上的数，取不到才回退 0。
# ══════════════════════════════════════════════════════════════════════════
_SCORE_PATTERNS = (
    r"最高\s*(\d+(?:\.\d+)?)\s*分",
    r"满分\s*(\d+(?:\.\d+)?)\s*分",
    r"共\s*(\d+(?:\.\d+)?)\s*分",
    r"(\d+(?:\.\d+)?)\s*分\s*/\s*项",
    r"每(?:一)?(?:项|个|份)\s*(?:得|计)?\s*(\d+(?:\.\d+)?)\s*分",
)
# 兜底用的"任意 N 分"，但要排除扣分语境
_SCORE_ANY = r"(\d+(?:\.\d+)?)\s*分"
# 前面 6 个字里出现这些词 = 这条是扣分/减免规则，不是分值
_DEDUCT_HINT = ("扣", "减", "下浮", "降低", "扣减")
_SCORE_LABEL_KEY = "score_source"


def _to_float(value) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"(\d+(?:\.\d+)?)", value)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return 0.0
    return 0.0


def parse_score_value(item: dict) -> tuple[float, str]:
    """取一个评分项的分值，返回 (分值, 来源)。

    招标解读给的评分项通常只有 name + 一段评分办法描述，分值是写在描述里的。
    直接从描述里抓"第一个 N 分"会抓错 —— 实测「投标总报价」的评分办法里
    开头就是"每高一个百分点扣1分"，于是被解析成 1 分（该项真实是价格分 35 分）。

    所以取值顺序是：
      ① 结构化字段 score/max_score/full_score/weight/value；
      ② "最高N分 / 满分N分 / 共N分 / N分每项" 这类明确写法；
      ③ 描述里所有" N 分"，**排除"扣N分/减N分"等扣分语境后取最大值**。
    都拿不到返回 0，并且把来源标出来，便于排查"这项分值怎么是 0"。
    """
    if not isinstance(item, dict):
        return 0.0, "none"
    for key in ("score", "max_score", "full_score", "weight", "value"):
        if key in item and item.get(key) not in (None, "", "-", "无"):
            got = _to_float(item.get(key))
            if got > 0:
                return got, f"field:{key}"
    desc = " ".join(
        str(item.get(k) or "") for k in ("description", "criteria", "standard", "detail", "rule")
    )
    for pat in _SCORE_PATTERNS:
        m = re.search(pat, desc)
        if m:
            got = _to_float(m.group(1))
            if got > 0:
                return got, "pattern"
    best = 0.0
    for m in re.finditer(_SCORE_ANY, desc):
        before = desc[max(0, m.start() - 6):m.start()]
        if any(h in before for h in _DEDUCT_HINT):
            continue
        got = _to_float(m.group(1))
        if got > best:
            best = got
    if best > 0:
        return best, "pattern:max"
    return 0.0, "none"


def extract_score_items(scoring_dim) -> list[dict]:
    """把 dimensions.scoring（或任何形状的评分数据）拍平成 [{name, score, ...}]。

    三类形状都要认，缺一类就会"找不到评分项"：
      ① {"scoring_items": [{name, description}, ...]}
      ② {"rows": [...]} / {"items": [...]} / {"score_matrix": [...]}
      ③ 只有权重没有明细：{"price_weight": "35分", "business_weight": "25分",
         "technical_weight": "40分"} —— 旧实现只认 list/dict，这三项是字符串，
         被整条丢掉，最后报"评分矩阵中无评分项"。
    """
    if isinstance(scoring_dim, list):
        raw = [x for x in scoring_dim if isinstance(x, dict)]
    elif isinstance(scoring_dim, dict):
        raw = []
        for key in ("scoring_items", "rows", "items", "score_matrix", "scoring_matrix",
                    "score_items", "matrix", "scores", "list", "detail"):
            val = scoring_dim.get(key)
            if isinstance(val, list) and val:
                raw = [x for x in val if isinstance(x, dict)]
                break
        if not raw:
            # 整个 dict 就是一行评分项
            if any(k in scoring_dim for k in ("name", "item", "criteria", "score")):
                raw = [scoring_dim]
    else:
        return []

    items: list[dict] = []
    for row in raw:
        name = str(row.get("name") or row.get("item") or row.get("category") or "").strip()
        if not name:
            continue
        score, src = parse_score_value(row)
        items.append({
            "name": name,
            "score": score,
            _SCORE_LABEL_KEY: src,
            "category": str(row.get("category") or "").strip(),
            "criteria": str(row.get("criteria") or row.get("description") or "").strip(),
        })

    if items:
        return items

    # ③ 只有权重：折算成三个"维度级"评分项，保证覆盖率检查至少有东西可比
    if isinstance(scoring_dim, dict):
        kw = (("business_weight", "商务"), ("technical_weight", "技术"), ("price_weight", "价格"))
        for key, label in kw:
            val = scoring_dim.get(key)
            if val in (None, "", "-", "无"):
                continue
            got = _to_float(val)
            if got > 0:
                items.append({"name": f"{label}部分（权重）", "score": got,
                              _SCORE_LABEL_KEY: f"field:{key}",
                              "category": label, "criteria": ""})
    return items


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
        # 大纲阶段已经算好的"评分项 → 章节id"权威映射。它是按一级章节名做过
        # 相似度匹配的，比这里重新猜一遍可靠，必须优先用。
        authoritative = ctx.parameters.get("score_mapping") or {}
        if not isinstance(authoritative, dict):
            authoritative = {}

        if not scoring_matrix:
            return SkillResult(success=False, error="无评分矩阵数据")

        score_items = self._extract_score_items(scoring_matrix)
        if not score_items:
            return SkillResult(success=False, error="评分矩阵中无评分项")

        # 兜底：调用方可能直接传 outlines.tree 这个 dict（历史 bug 就是这里被
        # isinstance(..., list) 判掉，导致 outline_sections 恒为 []、覆盖率恒为 0）
        titles = self._flatten_titles(outline_sections)

        coverage_map = {}
        covered_items = []
        uncovered_items = []
        total_score = 0.0

        for item in score_items:
            item_name = str(item.get("name") or item.get("item") or "").strip()
            if not item_name:
                continue
            # 分值统一走一个来源：parse_score_value 已经处理过"从描述里解析"，
            # 这里再加一层兜底，避免出现"分子有值、分母为0 → 覆盖率 4000%"。
            item_score = _to_float(item.get("score"))
            total_score += item_score

            matched_section = ""
            # ① 权威映射（大纲算的）优先
            for key, node in authoritative.items():
                if str(key).strip() == item_name and node:
                    matched_section = str(node)
                    break
            # ② 没映射过再按标题相似度找
            if not matched_section:
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
                    "suggestion": "建议添加章节覆盖此项",
                })

        covered_score = sum(_to_float(item["score"]) for item in covered_items)
        # 总分兜底：只有权重、没有明细分值的情况下用权重合计，避免分母为 0
        if total_score <= 0:
            total_score = self._weight_total(scoring_matrix) or covered_score
        coverage_rate = round(covered_score / total_score * 100, 1) if total_score > 0 else 0.0

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

    @staticmethod
    def _weight_total(matrix) -> float:
        """从"只有权重"的评分数据里取总分（商务+技术+价格）。"""
        if not isinstance(matrix, dict):
            return 0.0
        total = 0.0
        for key in ("business_weight", "technical_weight", "price_weight"):
            total += _to_float(matrix.get(key))
        return total

    def _extract_score_items(self, matrix) -> list[dict]:
        """拍平评分数据；分值从描述里解析（见模块级 parse_score_value）。

        旧实现只认 list/dict 类型的值，遇到"只有权重的三个字符串字段"直接丢掉，
        最终返回空列表并报"评分矩阵中无评分项"。
        """
        items = extract_score_items(matrix)
        if items:
            return items
        # 兼容"评分项就是字符串列表"的老形状
        raw: list = []
        if isinstance(matrix, list):
            raw = matrix
        elif isinstance(matrix, dict):
            for value in matrix.values():
                if isinstance(value, list):
                    raw.extend(value)
        out = []
        for x in raw:
            if isinstance(x, str) and x.strip():
                out.append({"name": x.strip(), "score": 0.0})
        return out

    def _flatten_titles(self, sections) -> list[str]:
        """把大纲（list / dict{'chapters':[...]} / 任意层级 children）拍平成标题列表。"""
        roots = sections
        if isinstance(sections, dict):
            roots = (
                sections.get("chapters")
                or sections.get("sections")
                or sections.get("outline")
                or []
            )
        if not isinstance(roots, list):
            return []

        titles: list[str] = []

        def walk(nodes):
            for node in nodes or []:
                if isinstance(node, dict):
                    title = str(node.get("title") or "").strip()
                    if title:
                        titles.append(title)
                    walk(node.get("children"))
                elif isinstance(node, str) and node.strip():
                    titles.append(node.strip())

        walk(roots)
        return titles

    def _find_matching_section(self, score_item: str, sections) -> str:
        """为评分项找最贴合的大纲章节标题，找不到返回 ""。

        旧实现用 `title in item or item in title` 子串判断，再把评分项按空格
        切成关键词 —— 中文没有空格，keywords 恒等于整串，第二条分支永远不命中；
        而评分项措辞（"企业类似业绩"）与章节标题（"企业信誉与类似业绩"）
        本来就不会字面相等，于是覆盖率长期为 0。
        现在复用 outline_gen_skill 的中文相似度（LCS + 特征词 + 字符Dice）。
        """
        item_name = str(score_item or "").strip()
        if not item_name:
            return ""

        titles = self._flatten_titles(sections)
        if not titles:
            return ""

        from services.generate.skills.outline_gen_skill import (
            SCORE_MATCH_THRESHOLD,
            best_matching_title,
        )

        title, score = best_matching_title(item_name, titles)
        return title if score >= SCORE_MATCH_THRESHOLD else ""
