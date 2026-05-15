from __future__ import annotations

import logging

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


class ContentGenSkill(Skill):
    name = "content_gen"
    description = "正文生成(四模式)，支持自动配图"
    category = "generate"
    version = "2.0.0"
    triggers = ["生成", "撰写", "写内容"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        mode = ctx.parameters.get("mode", "A")
        chapter_title = ctx.parameters.get("chapter_title", "")
        chapter_outline = ctx.parameters.get("chapter_outline", "")
        tender_context = ctx.parameters.get("tender_context", "")
        word_count_target = ctx.parameters.get("word_count", 3000)
        enable_illustration = ctx.parameters.get("enable_illustration", True)
        illustration_provider = ctx.parameters.get("illustration_provider", "default")
        illustration_size = ctx.parameters.get("illustration_size", "landscape_16_9")

        if mode == "A":
            result = await self._mode_a(ctx, chapter_title, chapter_outline, tender_context, word_count_target)
        elif mode == "B":
            result = await self._mode_b(ctx, chapter_title, chapter_outline, word_count_target)
        elif mode == "C":
            result = await self._mode_c(ctx, chapter_title, word_count_target)
        elif mode == "D":
            result = await self._mode_d(ctx, chapter_title, word_count_target)
        else:
            return SkillResult(success=False, error=f"未知模式: {mode}")

        if result.success and enable_illustration and chapter_title:
            result = await self._add_illustration(
                ctx, result, chapter_title,
                illustration_provider, illustration_size,
            )

        return result

    async def _add_illustration(
        self,
        ctx: SkillContext,
        content_result: SkillResult,
        chapter_title: str,
        provider: str,
        image_size: str,
    ) -> SkillResult:
        try:
            from services.generate.skills.ai_image_skill import AiImageSkill

            image_skill = AiImageSkill()
            image_ctx = SkillContext(
                project_id=ctx.project_id,
                db=ctx.db,
                llm=ctx.llm,
                parameters={
                    "prompt": f"Professional illustration for bidding document section: {chapter_title}",
                    "provider": provider,
                    "image_size": image_size,
                    "remove_watermark": True,
                    "chapter_title": chapter_title,
                    "style_hint": "professional,business,technical,clean,diagram",
                },
            )
            image_result = await image_skill.safe_execute(image_ctx)

            if image_result.success and image_result.data:
                if not content_result.data:
                    content_result.data = {}
                content_result.data["illustration"] = {
                    "image_url": image_result.data.get("image_url", ""),
                    "base64": image_result.data.get("base64", ""),
                    "provider": image_result.data.get("provider", ""),
                    "watermark_removed": image_result.data.get("watermark_removed", False),
                    "prompt": image_result.data.get("prompt", ""),
                }
            else:
                logger.info(f"Illustration generation skipped for '{chapter_title}': {image_result.error}")
                if not content_result.data:
                    content_result.data = {}
                content_result.data["illustration"] = None

        except Exception as e:
            logger.warning(f"Illustration generation failed for '{chapter_title}': {e}")
            if not content_result.data:
                content_result.data = {}
            content_result.data["illustration"] = None

        return content_result

    async def _mode_a(self, ctx, title, outline, tender_ctx, word_count):
        messages = [
            {
                "role": "system",
                "content": f"""你是标书撰写专家。请撰写"{title}"章节。
要求：
1. 内容必须针对本项目，不得使用通用模板套话
2. 字数约{word_count}字
3. 严格响应招标文件中的技术要求和评分标准
4. 在适当位置标注[插图位置]以便后续插入配图
5. 返回JSON: {{"content": "章节正文内容", "word_count": 实际字数, "illustration_suggestions": ["建议配图1描述", "建议配图2描述"]}}""",
            },
            {
                "role": "user",
                "content": f"章节大纲：{outline}\n\n招标要求上下文：\n{tender_ctx[:4000]}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.5)
        return SkillResult(success=True, data=result)

    async def _mode_b(self, ctx, title, outline, word_count):
        if not ctx.knowledge_base or not hasattr(ctx.knowledge_base, 'retrieve'):
            return await self._mode_a(ctx, title, outline, "", word_count)
        relevant_docs = await ctx.knowledge_base.retrieve(query=f"{title} {outline}", top_k=5)
        materials = "\n\n".join(doc["text"] for doc in relevant_docs)
        messages = [
            {
                "role": "system",
                "content": f"""你是标书撰写专家。基于提供的参考材料撰写"{title}"章节。
要求：整合参考材料，改写为适合本项目的表述，不得直接复制。
在适当位置标注[插图位置]以便后续插入配图。
返回JSON: {{"content": "章节正文", "sources": [引用来源列表], "illustration_suggestions": ["建议配图描述"]}}""",
            },
            {
                "role": "user",
                "content": f"章节大纲：{outline}\n\n参考材料：\n{materials[:6000]}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.4)
        return SkillResult(success=True, data=result)

    async def _mode_c(self, ctx, title, word_count):
        template = ctx.parameters.get("template_content", "")
        if not template:
            return SkillResult(success=False, error="未提供模板内容")
        messages = [
            {
                "role": "system",
                "content": f"""你是标书撰写专家。基于模板填充"{title}"章节。
保留模板结构和专业表述，替换项目特定信息。
在适当位置标注[插图位置]以便后续插入配图。
返回JSON: {{"content": "填充后的内容", "illustration_suggestions": ["建议配图描述"]}}""",
            },
            {
                "role": "user",
                "content": f"模板内容：\n{template[:6000]}\n\n项目信息：\n{ctx.parameters.get('project_info', '')}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.3)
        return SkillResult(success=True, data=result)

    async def _mode_d(self, ctx, title, word_count):
        external_data = ctx.parameters.get("external_data", "")
        if not external_data:
            return SkillResult(success=False, error="未提供外部数据")
        messages = [
            {
                "role": "system",
                "content": f"""你是标书撰写专家。整合外部数据撰写"{title}"章节。
在适当位置标注[插图位置]以便后续插入配图。
返回JSON: {{"content": "整合后的内容", "illustration_suggestions": ["建议配图描述"]}}""",
            },
            {
                "role": "user",
                "content": f"外部数据：\n{external_data[:6000]}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.4)
        return SkillResult(success=True, data=result)
