from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult

DIMENSION_WEIGHTS = {
    "field_overlap": 0.20,
    "price": 0.20,
    "metadata": 0.15,
    "structure": 0.15,
    "text": 0.20,
    "rare_sequences": 0.10,
}

DIMENSION_DESCRIPTIONS = {
    "field_overlap": "字段重叠度: 投标文件与招标文件关键字段(项目名称、编号、金额等)的一致性",
    "price": "价格风险: 报价合理性、是否超限价、是否异常低价",
    "metadata": "元数据风险: 文档属性、作者信息、修改时间等元数据异常",
    "structure": "结构完整性: 文档章节结构是否完整、是否缺失必要章节",
    "text": "文本质量: 错别字、标点、表述一致性等文本问题",
    "rare_sequences": "异常序列: 文档中是否存在异常字符序列、隐藏内容、可疑编码",
}


class RiskScoreSkill(Skill):
    name = "risk_score"
    description = "风险评分(C-08): 6维度加权风险评分"
    category = "check"
    version = "1.0.0"
    triggers = ["风险评分", "风险打分", "综合风险"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        check_results = ctx.parameters.get("check_results", {})
        if not check_results:
            return SkillResult(success=False, error="检查结果数据为空，无法进行风险评分")

        dimension_scores = {}
        for dim_id, weight in DIMENSION_WEIGHTS.items():
            dim_data = check_results.get(dim_id, {})
            score = self._compute_dimension_score(dim_id, dim_data)
            dimension_scores[dim_id] = {
                "score": score,
                "weight": weight,
                "weighted_score": round(score * weight, 2),
                "description": DIMENSION_DESCRIPTIONS[dim_id],
                "detail": self._dimension_detail(dim_id, dim_data, score),
            }

        composite_score = round(
            sum(d["weighted_score"] for d in dimension_scores.values()), 2
        )
        risk_level = self._determine_risk_level(composite_score)

        return SkillResult(
            success=True,
            data={
                "composite_score": composite_score,
                "risk_level": risk_level,
                "dimensions": dimension_scores,
                "summary": {
                    "highest_risk": max(dimension_scores, key=lambda k: dimension_scores[k]["score"]),
                    "lowest_risk": min(dimension_scores, key=lambda k: dimension_scores[k]["score"]),
                    "critical_dimensions": [
                        k for k, v in dimension_scores.items() if v["score"] >= 70
                    ],
                },
                "recommendations": self._generate_recommendations(dimension_scores, risk_level),
            },
        )

    def _compute_dimension_score(self, dim_id: str, dim_data: dict) -> float:
        if not dim_data:
            return 50.0

        if dim_id == "field_overlap":
            return self._score_field_overlap(dim_data)
        elif dim_id == "price":
            return self._score_price(dim_data)
        elif dim_id == "metadata":
            return self._score_metadata(dim_data)
        elif dim_id == "structure":
            return self._score_structure(dim_data)
        elif dim_id == "text":
            return self._score_text(dim_data)
        elif dim_id == "rare_sequences":
            return self._score_rare_sequences(dim_data)
        return 50.0

    def _score_field_overlap(self, data: dict) -> float:
        checks = data.get("checks", [])
        if not checks:
            return data.get("score", 50.0)
        failed = sum(1 for c in checks if isinstance(c, dict) and c.get("status") == "fail")
        total = len(checks)
        return min(100.0, round(failed / max(total, 1) * 100, 2))

    def _score_price(self, data: dict) -> float:
        checks = data.get("checks", [])
        if not checks:
            return data.get("score", 50.0)
        failed = sum(1 for c in checks if isinstance(c, dict) and c.get("status") == "fail")
        warning = sum(1 for c in checks if isinstance(c, dict) and c.get("status") == "warning")
        total = len(checks)
        return min(100.0, round((failed * 2 + warning) / max(total, 1) * 50, 2))

    def _score_metadata(self, data: dict) -> float:
        anomalies = data.get("anomalies", [])
        if not anomalies:
            return data.get("score", 20.0)
        return min(100.0, len(anomalies) * 25)

    def _score_structure(self, data: dict) -> float:
        missing = data.get("missing_sections", [])
        if not missing:
            return data.get("score", 10.0)
        return min(100.0, len(missing) * 15)

    def _score_text(self, data: dict) -> float:
        issues = data.get("issues", [])
        if not issues:
            return data.get("score", 10.0)
        high = sum(1 for i in issues if isinstance(i, dict) and i.get("severity") == "high")
        medium = sum(1 for i in issues if isinstance(i, dict) and i.get("severity") == "medium")
        return min(100.0, high * 20 + medium * 8 + (len(issues) - high - medium) * 3)

    def _score_rare_sequences(self, data: dict) -> float:
        sequences = data.get("rare_sequences", [])
        if not sequences:
            return data.get("score", 5.0)
        return min(100.0, len(sequences) * 30)

    def _dimension_detail(self, dim_id: str, dim_data: dict, score: float) -> str:
        if score >= 70:
            return f"高风险: {DIMENSION_DESCRIPTIONS[dim_id]}存在严重问题"
        elif score >= 40:
            return f"中风险: {DIMENSION_DESCRIPTIONS[dim_id]}存在部分问题"
        else:
            return f"低风险: {DIMENSION_DESCRIPTIONS[dim_id]}基本正常"

    def _determine_risk_level(self, composite_score: float) -> str:
        if composite_score >= 70:
            return "high"
        elif composite_score >= 40:
            return "medium"
        else:
            return "low"

    def _generate_recommendations(self, dimension_scores: dict, risk_level: str) -> list[str]:
        recommendations = []
        if risk_level == "high":
            recommendations.append("综合风险较高，建议全面复核投标文件后再行提交")
        elif risk_level == "medium":
            recommendations.append("存在中等风险，建议针对高风险维度进行重点修改")

        critical = [
            k for k, v in dimension_scores.items() if v["score"] >= 70
        ]
        for dim_id in critical:
            recommendations.append(
                f"【{DIMENSION_DESCRIPTIONS[dim_id]}】得分{dimension_scores[dim_id]['score']}，需重点整改"
            )

        if not recommendations:
            recommendations.append("整体风险较低，建议做常规复核后提交")
        return recommendations
