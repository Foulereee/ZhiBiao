from __future__ import annotations

import json

from core.skill_engine.base import Skill, SkillContext, SkillResult


class ScoringMatrixSkill(Skill):
    name = "scoring_matrix"
    description = "构建评分矩阵"
    category = "interpret"
    version = "1.0.0"
    triggers = ["评分矩阵", "评分标准"]

    # 判定"有内容":None / 空串 / "null" / "无" 等都算没提取到
    _EMPTY_WORDS = {"", "null", "none", "n/a", "无", "暂无", "未知", "待确认", "-", "--"}
    # 从招标文件正文中定位"评分办法"章节的关键词
    _SCORING_KEYS = (
        "评标办法", "评分办法", "评分标准", "评分细则", "评审因素",
        "评分表", "分值表", "打分", "得分", "分值",
    )
    _MAX_EXCERPT = 12000

    @classmethod
    def _is_empty(cls, value) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip().lower() in cls._EMPTY_WORDS
        if isinstance(value, (list, dict, tuple, set)):
            return len(value) == 0
        return False

    @classmethod
    def _scoring_excerpt(cls, text: str) -> str:
        """截取招标文件正文中最可能是「评分办法」的一段,避免把整篇文件喂给模型。"""
        if not isinstance(text, str) or not text.strip():
            return ""
        best = -1
        for kw in cls._SCORING_KEYS:
            pos = text.find(kw)
            if pos != -1 and (best == -1 or pos < best):
                best = pos
        if best == -1:
            return ""
        start = max(0, best - 200)
        return text[start:start + cls._MAX_EXCERPT]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        scoring_data = ctx.parameters.get("scoring_data") or {}
        document_text = ctx.parameters.get("document_text") or ""

        if isinstance(scoring_data, dict):
            has_data = any(not self._is_empty(v) for v in scoring_data.values())
        else:
            has_data = not self._is_empty(scoring_data)

        excerpt = self._scoring_excerpt(document_text)
        if has_data:
            user_content = f"评分标准数据：\n{json.dumps(scoring_data, ensure_ascii=False)}"
        else:
            # 解读阶段没提取到评分项(常见于:评分标准在附件表格里,或这份"招标文件"其实是资讯正文)
            # 兜底:直接从招标文件原文里截取评分办法章节重新构建
            if not excerpt:
                return SkillResult(
                    success=False,
                    error=(
                        "没有可用的评分数据：招标解读未提取到「评分标准/评分项」，"
                        "招标文件正文中也没有找到评标办法章节。"
                        "请确认上传的文件里确实包含评标办法(评分表)，或在「招标解读」中重新解读后再试。"
                    ),
                )
            user_content = (
                "以下是招标文件中截取的评标办法/评分标准原文，请据此构建评分矩阵"
                "（只依据原文，不要编造评分项）：\n" + excerpt
            )

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
                "content": user_content,
            },
        ]

        def _parse(payload, depth: int = 0) -> list:
            """兼容模型各种返回形状。

            实测 deepseek 会返回 {"project_no":…, "total_score":100, "score_matrix":[...]}
            ——键名是 score_matrix 而不是 rows/items,原实现只认 rows/items,
            导致评分项被丢弃、落库成 {"rows": []},下游再报"评分矩阵中无评分项"。
            """
            row_keys = (
                "rows", "items", "score_matrix", "scoring_matrix", "scoring_items",
                "matrix", "scores", "score_items", "data", "result", "list",
            )
            if depth > 3 or payload is None:
                return []
            if isinstance(payload, list):
                return [r for r in payload if isinstance(r, dict)]
            if isinstance(payload, dict):
                # 整个对象就是一行评分项
                if any(k in payload for k in ("score", "item", "seq", "criteria")) and not any(
                    isinstance(v, list) for v in payload.values()
                ):
                    return [payload]
                for key in row_keys:
                    if key in payload:
                        found = _parse(payload[key], depth + 1)
                        if found:
                            return found
                # 兜底:任何列表值里装着评分项对象
                for value in payload.values():
                    if isinstance(value, list):
                        found = _parse(value, depth + 1)
                        if found:
                            return found
            return []

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        matrix_rows = _parse(result)

        # 结构化数据太稀薄(只有评分方法/权重,没有评分细则)时模型可能仍返回空:
        # 再用招标文件原文重试一次,避免落库成 {"rows": []} 让后续检查报"无评分项"
        if not matrix_rows and has_data and excerpt:
            retry_messages = [
                messages[0],
                {
                    "role": "user",
                    "content": (
                        "以下是招标文件中截取的评标办法/评分标准原文，请据此构建评分矩阵"
                        "（只依据原文，不要编造评分项）：\n" + excerpt
                    ),
                },
            ]
            retry_result = await ctx.llm.collect_json(messages=retry_messages, temperature=0.1)
            matrix_rows = _parse(retry_result)

        if not matrix_rows:
            return SkillResult(
                success=False,
                error=(
                    "没有可用的评分数据：招标解读未提取到「评分标准/评分项」，"
                    "招标文件正文中也没有找到可解析的评标办法内容。"
                    "请确认上传的文件里确实包含评标办法(评分表)，或在「招标解读」中重新解读后再试。"
                ),
            )

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
