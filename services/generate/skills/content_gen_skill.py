from __future__ import annotations

import logging
import re

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_DATA_DEPENDENT_KEYWORDS = [
    "人员配置", "业绩", "资质证书", "资质证明",
    "项目案例", "成功案例", "合同", "营业执照",
    "财务报表", "审计报告", "纳税证明", "社保",
]

_TECHNICAL_KEYWORDS = [
    "技术方案", "实施方案", "系统架构", "技术路线",
    "总体设计", "解决方案", "平台架构", "系统设计",
]

_SERVICE_KEYWORDS = [
    "服务方案", "服务体系", "服务内容", "服务流程",
    "服务标准", "应急预案", "售后", "运维",
]

_MANAGEMENT_KEYWORDS = [
    "管理方案", "组织架构", "管理制度", "人员配置",
    "培训计划", "考核机制", "质量保障", "项目管理",
]


class ContentGenSkill(Skill):
    name = "content_gen"
    description = "正文生成(四模式)，支持章节上下文、RAG检索、自动配图"
    category = "generate"
    version = "4.0.0"
    triggers = ["生成", "撰写", "写内容"]

    MAX_CONTINUATION_ATTEMPTS = 2  # 最大续写次数
    SEGMENTED_THRESHOLD = 4000     # 超过此字数时启用分段生成

    async def execute(self, ctx: SkillContext) -> SkillResult:
        mode = ctx.parameters.get("mode", "A")
        chapter_title = ctx.parameters.get("chapter_title", "")
        chapter_outline = ctx.parameters.get("chapter_outline", "")
        chapter_context = ctx.parameters.get("chapter_context", "")
        tender_context = ctx.parameters.get("tender_context", "")
        scoring_context = ctx.parameters.get("scoring_context", "")
        mandatory_requirements = ctx.parameters.get("mandatory_requirements", "")
        word_count_target = ctx.parameters.get("word_count", self._infer_word_count(chapter_title))
        enable_illustration = ctx.parameters.get("enable_illustration", False)
        illustration_provider = ctx.parameters.get("illustration_provider", "default")
        illustration_size = ctx.parameters.get("illustration_size", "landscape_16_9")

        if self._is_data_dependent_chapter(chapter_title) and mode in ("A", "B"):
            rag_available = mode == "B" and ctx.knowledge_base and hasattr(ctx.knowledge_base, 'retrieve')
            if not rag_available:
                placeholder = self._generate_data_placeholder(chapter_title)
                return SkillResult(
                    success=True,
                    data={
                        "content": placeholder,
                        "word_count": len(placeholder),
                        "skipped": True,
                        "skip_reason": "data_dependent_no_rag",
                    },
                    warnings=[f"章节'{chapter_title}'需要真实企业数据，当前无知识库支撑，已生成占位提示"],
                )

        if mode == "A":
            # 超长章节启用分段生成策略
            if word_count_target >= self.SEGMENTED_THRESHOLD and chapter_outline:
                result = await self._segmented_generate(
                    ctx, chapter_title, chapter_outline, chapter_context,
                    tender_context, scoring_context, mandatory_requirements, word_count_target
                )
            else:
                result = await self._mode_a(ctx, chapter_title, chapter_outline, chapter_context, tender_context, scoring_context, mandatory_requirements, word_count_target)
        elif mode == "B":
            result = await self._mode_b(ctx, chapter_title, chapter_outline, chapter_context, tender_context, scoring_context, mandatory_requirements, word_count_target)
        elif mode == "C":
            result = await self._mode_c(ctx, chapter_title, word_count_target)
        elif mode == "D":
            result = await self._mode_d(ctx, chapter_title, word_count_target)
        else:
            return SkillResult(success=False, error=f"未知模式: {mode}")

        if result.success and result.data and not result.data.get("skipped"):
            content = result.data.get("content", "")
            # 截断检测与续写
            content = await self._ensure_complete(ctx, content, chapter_title, word_count_target)
            content = self._post_process(content, chapter_title)
            result.data["content"] = content
            result.data["word_count"] = len(content)

        if result.success and enable_illustration and chapter_title and not result.data.get("skipped"):
            result = await self._add_illustration(
                ctx, result, chapter_title,
                illustration_provider, illustration_size,
            )

        return result

    @staticmethod
    def _infer_word_count(title: str) -> int:
        for kw in _TECHNICAL_KEYWORDS:
            if kw in title:
                return 4000
        for kw in _SERVICE_KEYWORDS:
            if kw in title:
                return 3500
        for kw in _MANAGEMENT_KEYWORDS:
            if kw in title:
                return 3000
        return 2500

    @staticmethod
    def _is_data_dependent_chapter(title: str) -> bool:
        return any(kw in title for kw in _DATA_DEPENDENT_KEYWORDS)

    @staticmethod
    def _generate_data_placeholder(title: str) -> str:
        return (
            f"### {title}\n\n"
            f"> **[占位提示]** 本章节需要根据公司实际情况填写真实数据，"
            f"包括但不限于：企业资质证书、项目业绩案例、人员配置信息等。\n\n"
            f"请在知识库中上传相关材料后重新生成，或手动补充以下内容：\n\n"
            f"1. 相关资质证书及有效期\n"
            f"2. 近三年同类项目业绩\n"
            f"3. 项目团队人员资质及经验\n"
            f"4. 其他证明材料\n"
        )

    @staticmethod
    def _post_process(content: str, chapter_title: str) -> str:
        from services.generate.skills.content_cleaner import clean_generated_content
        return clean_generated_content(content, chapter_title)

    async def _ensure_complete(
        self, ctx: SkillContext, content: str, chapter_title: str, word_count: int
    ) -> str:
        """检测内容是否被截断，如果是则尝试续写。

        策略：
        1. 检测内容是否以完整句子结尾
        2. 如果不完整，提取已生成内容作为上下文，请求LLM续写
        3. 最多续写 MAX_CONTINUATION_ATTEMPTS 次
        """
        from services.generate.skills.content_cleaner import is_content_truncated, get_last_complete_section

        for attempt in range(self.MAX_CONTINUATION_ATTEMPTS):
            if not is_content_truncated(content):
                break

            logger.warning(
                f"[ContentGenSkill] 内容截断检测触发 "
                f"chapter='{chapter_title}', attempt={attempt+1}, "
                f"当前长度={len(content)}字符"
            )

            _complete, incomplete_tail = get_last_complete_section(content)
            # 取已生成内容的最后 800 字符作为续写上下文
            continuation_context = content[-800:] if len(content) > 800 else content

            continuation_messages = [
                {
                    "role": "system",
                    "content": (
                        f"你是投标文件撰写专家。请继续完成\u201c{chapter_title}\u201d章节的剩余内容。\n"
                        "要求：\n"
                        "1. 从上次中断的地方继续，不要重复已有内容\n"
                        "2. 确保内容完整，以完整的句子结尾\n"
                        "3. 保持与已有内容一致的语言风格和专业性\n"
                        "4. 直接输出续写内容，不要重复标题"
                    ),
                },
                {
                    "role": "user",
                    "content": f"已生成的内容末尾：\n{continuation_context}\n\n请从这里继续写下去。",
                },
            ]

            try:
                continuation = await ctx.llm.chat(
                    messages=continuation_messages,
                    temperature=0.5,
                    max_tokens=min(word_count, 4096),
                )
                if isinstance(continuation, str) and continuation.strip():
                    content = content.rstrip() + "\n\n" + continuation.strip()
                    logger.info(
                        f"[ContentGenSkill] 续写完成 attempt={attempt+1}, "
                        f"新增{len(continuation)}字符, 总长度={len(content)}字符"
                    )
                else:
                    logger.warning(f"[ContentGenSkill] 续写返回空内容 attempt={attempt+1}")
                    break
            except Exception as e:
                logger.error(f"[ContentGenSkill] 续写失败 attempt={attempt+1}: {e}")
                break

        return content

    def _build_system_prompt(self, title: str, word_count: int) -> str:
        return f"""你是具有十年以上经验的资深投标文件撰写专家。请撰写\u201c{title}\u201d章节。

【撰写规范】
1. 结构要求：
   - 本章必须包含至少 3 个二级节（用 ### 标记）
   - 每个二级节下必须包含至少 2-3 个三级小节（用 #### 标记）
   - 每个三级小节正文不少于 500 字，重要小节应达到 800-1000 字
   - 可适当使用表格展示对比、清单、计划等结构化信息

2. 语言风格：
   - 使用正式、严谨、专业的投标文件语言
   - 使用\u201c本公司\u201d、\u201c投标人\u201d指代己方，\u201c采购人\u201d、\u201c招标人\u201d指代对方
   - 禁止口语化表达、禁止\u201c我们\u201d、\u201c你们\u201d
   - 禁止模糊表述如\u201c如有需要\u201d、\u201c可以考虑\u201d、\u201c大概\u201d

3. 内容要求：
   - 每个要点必须展开论述，给出具体措施、方法、流程或标准
   - 技术方案章节应包含：总体设计思路、技术架构、关键技术、实施方案、质量保障
   - 服务方案章节应包含：服务体系、服务内容、服务流程、服务标准、应急预案
   - 管理方案章节应包含：组织架构、管理制度、人员配置、培训计划、考核机制

4. 禁止事项：
   - 不得编造企业名称、资质证书、项目案例、人员信息、合同金额
   - 不得使用代码块包裹正文
   - 表格内不得出现 Markdown 格式标记

5. 篇幅要求：
   - 每个三级小节正文不少于 500 字
   - 本章节总字数不少于 {word_count} 字

6. 输出格式：
   - 直接输出章节正文（从 ### 二级节标题开始）
   - 不要输出章节一级标题
   - 不要输出任何解释、说明或总结

7. 质量要求（极其重要）：
   - 每个字词只能出现一次，绝对禁止重复（如\u201c采用采用\u201d\u201c包括包括\u201d\u201c项目项目\u201d）
   - 禁止输出任何无意义的单字母（如\u201cz\u201d\u201cx\u201d等）
   - 禁止输出乱码或不可读字符
   - 标题编号必须规范（如 ### 1.1、#### 1.1.1），禁止出现\u201c1####\u201d\u201cd D.\u201d等格式
   - 每个标点符号只用一次，禁止重复（如\u201c。。。。\u201d）
   - 输出前请逐字检查，确保无重复词、无错字、无乱码"""

    def _build_messages(
        self,
        system_prompt: str,
        chapter_outline: str,
        chapter_context: str,
        tender_context: str,
        scoring_context: str,
        mandatory_requirements: str,
        extra_user_content: str = "",
    ) -> list[dict]:
        messages = [{"role": "system", "content": system_prompt}]

        if tender_context:
            messages.append({
                "role": "user",
                "content": f"【招标要求上下文】\n{tender_context[:3000]}",
            })

        if chapter_context:
            messages.append({
                "role": "user",
                "content": chapter_context,
            })

        if scoring_context:
            messages.append({
                "role": "user",
                "content": scoring_context,
            })

        if mandatory_requirements:
            messages.append({
                "role": "user",
                "content": f"【必须响应的强制性要求】\n{mandatory_requirements[:2000]}",
            })

        user_parts = []
        if chapter_outline:
            user_parts.append(f"【章节大纲】\n{chapter_outline[:2000]}")
        if extra_user_content:
            user_parts.append(extra_user_content)

        if user_parts:
            messages.append({
                "role": "user",
                "content": "\n\n".join(user_parts),
            })

        return messages

    async def _mode_a(self, ctx, title, outline, chapter_context, tender_ctx, scoring_ctx, mandatory_reqs, word_count):
        system_prompt = self._build_system_prompt(title, word_count)
        messages = self._build_messages(
            system_prompt=system_prompt,
            chapter_outline=outline,
            chapter_context=chapter_context,
            tender_context=tender_ctx,
            scoring_context=scoring_ctx,
            mandatory_requirements=mandatory_reqs,
        )
        result = await ctx.llm.collect_json(
            messages=messages,
            temperature=0.5,
            max_tokens=min(word_count * 2, 8192),
        )
        return SkillResult(success=True, data=result)

    async def _mode_b(self, ctx, title, outline, chapter_context, tender_ctx, scoring_ctx, mandatory_reqs, word_count):
        rag_context = ""
        if ctx.knowledge_base and hasattr(ctx.knowledge_base, 'retrieve'):
            try:
                query = f"{title} {outline[:200]}" if outline else title
                relevant_docs = await ctx.knowledge_base.retrieve(query=query, top_k=5)
                if relevant_docs:
                    rag_context = "\n\n".join(
                        f"<knowledge_content>\n{doc.get('text', doc.get('content', ''))[:800]}\n</knowledge_content>"
                        for doc in relevant_docs
                    )
            except Exception as e:
                logger.warning(f"RAG检索失败，降级为模式A: {e}")
                return await self._mode_a(ctx, title, outline, chapter_context, tender_ctx, scoring_ctx, mandatory_reqs, word_count)
        else:
            logger.info("知识库不可用，降级为模式A")
            return await self._mode_a(ctx, title, outline, chapter_context, tender_ctx, scoring_ctx, mandatory_reqs, word_count)

        system_prompt = self._build_system_prompt(title, word_count)
        system_prompt += "\n\n【额外要求】基于提供的参考材料撰写，整合参考材料改写为适合本项目的表述，不得直接复制。"

        messages = self._build_messages(
            system_prompt=system_prompt,
            chapter_outline=outline,
            chapter_context=chapter_context,
            tender_context=tender_ctx,
            scoring_context=scoring_ctx,
            mandatory_requirements=mandatory_reqs,
            extra_user_content=f"【参考材料（请优先引用其中的具体数据和案例）】\n{rag_context[:6000]}",
        )

        result = await ctx.llm.collect_json(
            messages=messages,
            temperature=0.4,
            max_tokens=min(word_count * 2, 8192),
        )
        return SkillResult(success=True, data=result)

    async def _mode_c(self, ctx, title, word_count):
        template = ctx.parameters.get("template_content", "")
        if not template:
            return SkillResult(success=False, error="未提供模板内容")

        system_prompt = self._build_system_prompt(title, word_count)
        system_prompt += "\n\n【额外要求】基于提供的模板填充，保留模板结构和专业表述，替换项目特定信息。"

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"【模板内容】\n{template[:6000]}\n\n【项目信息】\n{ctx.parameters.get('project_info', '')}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.3)
        return SkillResult(success=True, data=result)

    async def _mode_d(self, ctx, title, word_count):
        external_data = ctx.parameters.get("external_data", "")
        if not external_data:
            return SkillResult(success=False, error="未提供外部数据")

        system_prompt = self._build_system_prompt(title, word_count)
        system_prompt += "\n\n【额外要求】整合提供的外部数据撰写，确保数据准确引用。"

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"【外部数据】\n{external_data[:6000]}",
            },
        ]
        result = await ctx.llm.collect_json(messages=messages, temperature=0.4)
        return SkillResult(success=True, data=result)

    async def _segmented_generate(
        self, ctx, title, outline, chapter_context,
        tender_ctx, scoring_ctx, mandatory_reqs, word_count
    ) -> SkillResult:
        """超长章节分段生成策略。

        流程：
        1. 先让 LLM 规划章节分段方案（将大纲拆分为多个小节）
        2. 逐节独立生成（每节 1500-2500 字）
        3. 合并所有节的内容
        """
        import asyncio

        logger.info(
            f"[ContentGenSkill] 分段生成模式: chapter='{title}', "
            f"target={word_count}字"
        )

        # Step 1: 规划分段方案
        plan_messages = [
            {
                "role": "system",
                "content": (
                    "你是投标文件规划专家。将章节大纲拆分为多个独立的小节，"
                    "每个小节对应一个完整的子章节。\n"
                    "返回JSON格式：{\"sections\": [{\"title\": \"小节标题\", \"word_target\": 1500}]}\n"
                    "每个小节目标字数1500-2500字，总数加起来应达到章节总字数要求。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"章节标题：{title}\n"
                    f"章节大纲：\n{outline[:2000]}\n"
                    f"章节总字数要求：{word_count}字\n"
                    "请拆分为多个小节。"
                ),
            },
        ]

        try:
            plan = await ctx.llm.collect_json(messages=plan_messages, temperature=0.3)
        except Exception as e:
            logger.warning(f"[ContentGenSkill] 分段规划失败，降级为单次生成: {e}")
            return await self._mode_a(
                ctx, title, outline, chapter_context,
                tender_ctx, scoring_ctx, mandatory_reqs, word_count
            )

        sections = plan.get("sections", [])
        if not sections or len(sections) < 2:
            logger.info("[ContentGenSkill] 分段方案不足，降级为单次生成")
            return await self._mode_a(
                ctx, title, outline, chapter_context,
                tender_ctx, scoring_ctx, mandatory_reqs, word_count
            )

        logger.info(f"[ContentGenSkill] 分段方案: {len(sections)}个小节")

        # Step 2: 逐节独立生成
        async def _gen_section(idx: int, section: dict) -> tuple[int, str]:
            sec_title = section.get("title", f"小节{idx+1}")
            sec_words = section.get("word_target", 1500)
            system_prompt = self._build_system_prompt(f"{title} - {sec_title}", sec_words)
            messages = self._build_messages(
                system_prompt=system_prompt,
                chapter_outline=f"当前小节: {sec_title}\n{outline[:1000]}",
                chapter_context=chapter_context,
                tender_context=tender_ctx,
                scoring_context=scoring_ctx,
                mandatory_requirements=mandatory_reqs,
            )
            try:
                result = await ctx.llm.collect_json(
                    messages=messages,
                    temperature=0.5,
                    max_tokens=min(sec_words * 2, 6144),
                )
                content = result.get("content", "") if isinstance(result, dict) else str(result)
                logger.info(f"[ContentGenSkill] 小节 {idx+1}/{len(sections)} '{sec_title}' 生成 {len(content)}字")
                return (idx, content)
            except Exception as e:
                logger.error(f"[ContentGenSkill] 小节 '{sec_title}' 生成失败: {e}")
                return (idx, "")

        # 最多3并发
        semaphore = asyncio.Semaphore(3)

        async def _limited(idx, sec):
            async with semaphore:
                return await _gen_section(idx, sec)

        tasks = [_limited(i, s) for i, s in enumerate(sections)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Step 3: 按索引合并
        section_contents = [""] * len(sections)
        for r in results:
            if isinstance(r, Exception):
                continue
            idx, content = r
            section_contents[idx] = content

        full_content = "\n\n".join(c for c in section_contents if c)
        logger.info(
            f"[ContentGenSkill] 分段生成完成: {len(sections)}小节, "
            f"总字数={len(full_content)}"
        )

        return SkillResult(success=True, data={"content": full_content})

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
