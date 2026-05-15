from __future__ import annotations

import json

from core.skill_engine.base import Skill, SkillContext, SkillResult


class ScoringMatrixSkill(Skill):
    name = "scoring_matrix"
    description = "构建评分矩阵"
    category = "interpret"
    version = "1.0.0"
    triggers = ["评分矩阵", "评分标准"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        scoring_data = ctx.parameters.get("scoring_data", {})
        if not scoring_data:
            return SkillResult(success=False, error="评分数据为空")

        messages = [
            {
                "role": "system",
                "content": """你是招标文件评分矩阵构建专家。
将评分标准转换为结构化矩阵，每个评分项一行。
返回JSON数组，每项包含：
- seq: 序号
- category: 类别(商务/技术/价格)
- item: 评分项名称
- score: 分值
- criteria: 评分标准描述
- response_section: 建议应答章节(如"3.1技术方案")
- status: 状态(pending)""",
            },
            {
                "role": "user",
                "content": f"评分标准数据：\n{json.dumps(scoring_data, ensure_ascii=False)}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        if isinstance(result, list):
            matrix_rows = result
        elif isinstance(result, dict):
            matrix_rows = result.get("rows", result.get("items", []))
            if not isinstance(matrix_rows, list):
                matrix_rows = []
        else:
            matrix_rows = []

        total_score = sum(row.get("score", 0) for row in matrix_rows)
        category_scores = {}
        for row in matrix_rows:
            cat = row.get("category", "未分类")
            category_scores[cat] = category_scores.get(cat, 0) + row.get("score", 0)

        return SkillResult(
            success=True,
            data={
                "rows": matrix_rows,
                "total_score": total_score,
                "category_scores": category_scores,
                "row_count": len(matrix_rows),
            },
        )
