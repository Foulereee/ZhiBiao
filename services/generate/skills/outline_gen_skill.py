from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class OutlineGenSkill(Skill):
    name = "outline_gen"
    description = "大纲生成(双模式)"
    category = "generate"
    version = "1.0.0"
    triggers = ["大纲", "目录", "提纲"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        mode = ctx.parameters.get("mode", "aligned")
        document_text = ctx.parameters.get("document_text", "")
        scoring_matrix = ctx.parameters.get("scoring_matrix", {})

        if mode == "free":
            return await self._free_mode(ctx, document_text)
        else:
            return await self._aligned_mode(ctx, document_text, scoring_matrix)

    async def _free_mode(self, ctx: SkillContext, text: str) -> SkillResult:
        messages = [
            {
                "role": "system",
                "content": """你是标书大纲生成专家。根据招标文件生成三级目录大纲。
返回JSON格式：
{"chapters": [{"id": "1", "title": "章节标题", "level": 1, "children": [{"id": "1.1", "title": "子章节", "level": 2, "children": []}]}]}
标准标书结构：投标函→资格审查→技术标→商务标→售后服务""",
            },
            {
                "role": "user",
                "content": f"招标文件内容：\n{text[:8000]}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.3)
        return SkillResult(success=True, data={"outline": result, "mode": "free"})

    async def _aligned_mode(self, ctx: SkillContext, text: str, scoring_matrix: dict) -> SkillResult:
        scoring_items = scoring_matrix.get("rows", [])
        if not scoring_items:
            return await self._free_mode(ctx, text)
        scoring_text = "\n".join(
            f"- [{item.get('category', '')}] {item.get('item', '')} ({item.get('score', 0)}分)"
            for item in scoring_items
        )
        messages = [
            {
                "role": "system",
                "content": """你是标书大纲生成专家。根据评分标准生成对齐评分项的三级目录。
要求：每个评分项必须有对应的应答章节，章节标题应体现评分项关键词。
返回JSON: {"chapters": [...], "score_mapping": {"评分项ID": "章节ID"}}""",
            },
            {
                "role": "user",
                "content": f"招标文件摘要：\n{text[:4000]}\n\n评分标准：\n{scoring_text}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.3)
        return SkillResult(success=True, data={"outline": result, "mode": "aligned"})
