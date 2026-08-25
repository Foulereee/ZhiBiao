"""大纲生成 Skill v7.0.0 — 结构模板融合 + 截取优化 + 精准映射。

核心优化：
1. Step2 并行生成：所有一级章节的二三级子目录同时请求，而非串行
2. 并发控制：最多4个并发LLM请求，避免API限流
3. 超时控制：单个子目录生成超过120s则跳过
4. 结果校验 + 自动降级
5. 结构模板融合：将 structure_sections 注入 prompt 引导 LLM
6. 增大文本截取限制，减少信息丢失
7. 评分项映射改用词级匹配 + 关键特征词加权
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 4
STEP2_TIMEOUT = 120

# 文本截取限制（v7.0.0: 大幅放宽以减少信息丢失）
STEP1_TEXT_LIMIT = 15000
STEP2_SCORING_LIMIT = 1500
ONE_SHOT_TEXT_LIMIT = 12000
ONE_SHOT_RETRY_TEXT_LIMIT = 6000
STEP1_DESC_LIMIT = 150
STEP2_DESC_LIMIT = 200

# 评分项映射：停用词（常见通用词，不参与匹配评分）
_SCORING_STOP_WORDS = set("的方案和管理与及其等在对于了是对")


def _format_structure_sections(sections: list[dict]) -> str:
    """将结构模板 sections 格式化为 prompt 注入文本。"""
    if not sections:
        return ""
    lines = ["参考结构模板（请在以下框架基础上根据招标文件进行调整和补充）："]
    for sec in sections:
        title = sec.get("title", "")
        hint = sec.get("content_hint", "")
        page = sec.get("page_target", 0)
        level = sec.get("level", 1)
        prefix = "  " * (level - 1) + "- "
        line = f"{prefix}{title}"
        extras = []
        if hint:
            extras.append(f"内容提示: {hint}")
        if page:
            extras.append(f"目标{page}页")
        if extras:
            line += f"（{'，'.join(extras)}）"
        lines.append(line)
    return "\n".join(lines)


def _fix_outline_node(node: dict, parent_id: str = "", seq: int = 0, level: int = 1) -> dict:
    node_id = str(node.get("id", "")).strip()
    if not node_id or node_id in (" ", "null", "None"):
        node_id = f"{parent_id}.{seq}" if parent_id else str(seq)
    try:
        node_level = int(node.get("level", level))
    except (ValueError, TypeError):
        node_level = level
    title = str(node.get("title", "")).strip()
    title = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", title)
    if re.match(r"^[:\s]*null\s*$", title, re.IGNORECASE):
        title = ""
    title = re.sub(r"^:\s*", "", title)
    if not title:
        title = f"章节 {node_id}"
    children = node.get("children", [])
    if not isinstance(children, list):
        children = []
    fixed_children = []
    for i, child in enumerate(children):
        if isinstance(child, dict):
            fixed_children.append(_fix_outline_node(child, node_id, i + 1, node_level + 1))
    return {"id": node_id, "title": title, "level": node_level, "children": fixed_children}


def _renumber_outline(items: list, parent: str = "") -> list:
    results = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        new_id = f"{parent}.{idx + 1}" if parent else str(idx + 1)
        entry = {"id": new_id, "title": item.get("title", ""), "level": item.get("level", 1)}
        if item.get("describe"):
            entry["describe"] = item["describe"]
        if item.get("content"):
            entry["content"] = item["content"]
        children = item.get("children", [])
        if children and isinstance(children, list):
            entry["children"] = _renumber_outline(children, new_id)
        results.append(entry)
    return results


def _fix_outline(data: dict) -> dict:
    if not isinstance(data, dict):
        return {"chapters": []}
    chapters = data.get("chapters", [])
    if not isinstance(chapters, list):
        for key in ("sections", "items", "nodes", "outline"):
            alt = data.get(key)
            if isinstance(alt, list):
                chapters = alt
                break
        else:
            chapters = []
    fixed_chapters = []
    for i, chapter in enumerate(chapters):
        if isinstance(chapter, dict):
            fixed_chapters.append(_fix_outline_node(chapter, "", i + 1, 1))
        elif isinstance(chapter, str):
            fixed_chapters.append({
                "id": str(i + 1), "title": chapter.strip() or f"章节 {i+1}",
                "level": 1, "children": [],
            })
    for ch in fixed_chapters:
        if not ch.get("children"):
            ch["children"] = _generate_default_sub_chapters(ch.get("title", ""), ch.get("id", ""))
    fixed_chapters = _renumber_outline(fixed_chapters)
    result = {"chapters": fixed_chapters}
    score_mapping = data.get("score_mapping", {})
    if score_mapping and isinstance(score_mapping, dict):
        result["score_mapping"] = score_mapping
    return result


def _validate_outline(outline: dict) -> str | None:
    chapters = outline.get("chapters", [])
    if not chapters:
        return "大纲章节为空"
    if len(chapters) < 5:
        return f"一级目录数量过少({len(chapters)}个)，至少需要5个"
    placeholder_patterns = [r"^章节\d+$", r"^第\d+章", r"^Chapter\s*\d+", r"^开章$", r"^章节$"]
    for ch in chapters:
        title = ch.get("title", "").strip()
        for pat in placeholder_patterns:
            if re.match(pat, title):
                return f"存在占位符标题: '{title}'，请重新生成"
    chapters_with_children = sum(1 for c in chapters if c.get("children"))
    if chapters_with_children < len(chapters) * 0.5:
        return f"大部分一级目录缺少二级子目录({chapters_with_children}/{len(chapters)})"
    return None


def _generate_default_sub_chapters(title: str, parent_id: str) -> list[dict]:
    generic_subs = ["总体概述", "实施方案", "保障措施"]
    result = []
    for i, sub_title in enumerate(generic_subs):
        sub_id = f"{parent_id}.{i+1}" if parent_id else str(i+1)
        result.append({
            "id": sub_id,
            "title": f"{title}{sub_title}",
            "level": 2,
            "children": [],
        })
    return result


def _tokenize_chinese(text: str) -> set[str]:
    """将中文文本拆分为2-4字特征词组，用于评分项映射。"""
    text = re.sub(r"[^\u4e00-\u9fff\w]", "", text)
    tokens = set()
    for length in (4, 3, 2):
        for i in range(len(text) - length + 1):
            token = text[i:i + length]
            # 过滤纯停用词组合
            if not all(c in _SCORING_STOP_WORDS for c in token):
                tokens.add(token)
    return tokens


def _build_step1_messages(
    text: str, scoring_text: str, mode: str, structure_hint: str = ""
) -> list[dict]:
    if mode == "aligned" and scoring_text:
        system_msg = (
            "你是一个专业的标书编写专家。根据提供的招标文件和评分标准，"
            "生成投标文件的一级目录结构。\n\n"
            "要求：\n"
            "1. 一级目录名称要专业、准确，符合投标文件规范。\n"
            "2. 一级目录名称要尽量与评分标准中的章节名称一致；"
            "如果评分标准中没有明确章节名称，则结合内容总结一级目录名称。\n"
            "3. 一级目录必须覆盖所有评分项。\n"
            "4. 一般包含8-15个一级章节。\n"
            "5. 必须包含：投标函、资格审查、技术方案、商务报价等基本章节。\n"
            "6. 【严禁】使用'章节N'、'第N章'等占位符作为标题，"
            "每个标题必须是有实际含义的专业名称。\n"
            "7. 【严禁】生成空章节（没有description的章节），"
            "每个章节的description必须具体说明本章要写什么。\n"
            "8. 返回标准 JSON 格式，只返回 JSON，不要输出任何其他内容。\n\n"
            "JSON 格式要求：\n"
            '{"chapters": [{"title": "章节标题", "description": "本章内容概述(20字以上)"}]}'
        )
        user_msgs = [
            {"role": "user", "content": f"招标文件摘要：\n{text[:STEP1_TEXT_LIMIT]}"},
            {"role": "user", "content": f"评分标准：\n{scoring_text}"},
        ]
        if structure_hint:
            user_msgs.insert(2, {"role": "user", "content": structure_hint})
        user_msgs.append(
            {"role": "user", "content": "请根据以上招标文件和评分标准，生成投标文件的一级目录结构。每个标题必须有实际含义，不要使用占位符。"}
        )
    else:
        system_msg = (
            "你是一个专业的标书编写专家。根据提供的招标文件内容，"
            "生成投标文件的一级目录结构。\n\n"
            "要求：\n"
            "1. 一级目录名称要专业、准确，符合投标文件规范。\n"
            "2. 一般包含8-15个一级章节。\n"
            "3. 必须包含：投标函、资格审查、技术方案、商务报价等基本章节。\n"
            "4. 【严禁】使用'章节N'、'第N章'等占位符作为标题，"
            "每个标题必须是有实际含义的专业名称。\n"
            "5. 【严禁】生成空章节，每个章节的description必须具体说明本章要写什么。\n"
            "6. 返回标准 JSON 格式，只返回 JSON，不要输出任何其他内容。\n\n"
            "JSON 格式要求：\n"
            '{"chapters": [{"title": "章节标题", "description": "本章内容概述(20字以上)"}]}'
        )
        user_msgs = [
            {"role": "user", "content": f"招标文件摘要：\n{text[:STEP1_TEXT_LIMIT]}"},
        ]
        if structure_hint:
            user_msgs.append({"role": "user", "content": structure_hint})
        user_msgs.append(
            {"role": "user", "content": "请根据以上招标文件内容，生成投标文件的一级目录结构。每个标题必须有实际含义，不要使用占位符。"}
        )
    return [{"role": "system", "content": system_msg}] + user_msgs


def _build_step2_messages(chapter_title: str, chapter_desc: str, text: str, scoring_text: str) -> list[dict]:
    system_msg = (
        "你是专业的标书目录规划专家。为指定一级章节生成二三级子目录。\n\n"
        "【严格规则】\n"
        "1. 只生成3-5个二级目录，每个二级下2-3个三级目录\n"
        "2. 每个目录节点只有title字段，不要添加description等其他字段\n"
        "3. 不要生成超过3级的目录\n"
        "4. 只返回JSON，不要输出任何解释\n\n"
        "【输出格式】\n"
        '{"children": [{"title": "二级标题", "children": [{"title": "三级标题"}]}]}'
    )
    user_content = f"一级章节：{chapter_title}"
    if chapter_desc:
        user_content += f"\n说明：{chapter_desc[:STEP2_DESC_LIMIT]}"
    user_msgs = [{"role": "user", "content": user_content}]
    if scoring_text:
        user_msgs.append({"role": "user", "content": f"相关评分标准：\n{scoring_text[:STEP2_SCORING_LIMIT]}"})
    user_msgs.append({"role": "user", "content": "请生成该一级章节下的二三级子目录。"})
    return [{"role": "system", "content": system_msg}] + user_msgs


def _build_one_shot_messages(text: str, scoring_text: str, mode: str, structure_hint: str = "") -> list[dict]:
    system_msg = (
        "你是具有十年经验的资深投标文件目录规划专家。"
        "请根据招标文件内容生成完整的三级目录大纲。\n\n"
        "要求：\n"
        "1. 目录结构要全面覆盖投标文件的所有必要章节。\n"
        "2. 章节名称要专业、准确，符合投标文件规范。\n"
        "3. 一级目录8-15个，每个一级目录下3-6个二级节，每个二级节下2-4个三级小节。\n"
        "4. 必须包含：投标函、资格审查、技术方案、商务报价等基本章节。\n"
        "5. 返回标准 JSON 格式，只返回 JSON，不要输出任何其他内容。\n\n"
        "JSON 格式要求：\n"
        '{"chapters": [{"id": "1", "title": "章节标题", "level": 1, '
        '"children": [{"id": "1.1", "title": "子标题", "level": 2, '
        '"children": [{"id": "1.1.1", "title": "小节标题", "level": 3, "children": []}]}]}]}'
    )
    user_msgs = [{"role": "user", "content": f"招标文件摘要：\n{text[:ONE_SHOT_TEXT_LIMIT]}"}]
    if scoring_text and mode == "aligned":
        user_msgs.append({"role": "user", "content": f"评分标准：\n{scoring_text}"})
    if structure_hint:
        user_msgs.append({"role": "user", "content": structure_hint})
    user_msgs.append({"role": "user", "content": "请生成完整的三级目录大纲，确保覆盖所有评分要点。"})
    return [{"role": "system", "content": system_msg}] + user_msgs


class OutlineGenSkill(Skill):
    name = "outline_gen"
    description = "大纲生成(并行分步模式+自动降级)"
    category = "generate"
    version = "7.0.0"
    triggers = ["大纲", "目录", "提纲"]

    STEP2_MAX_TOKENS = 2048

    async def execute(self, ctx: SkillContext) -> SkillResult:
        mode = ctx.parameters.get("mode", "aligned")
        document_text = ctx.parameters.get("document_text", "")
        scoring_matrix = ctx.parameters.get("scoring_matrix", {})
        structure_sections = ctx.parameters.get("structure_sections", [])

        # 格式化结构模板提示
        structure_hint = _format_structure_sections(structure_sections) if structure_sections else ""

        logger.info(
            f"[OutlineGenSkill] mode={mode}, 文档长度={len(document_text)}字符, "
            f"scoring_matrix_rows={len(scoring_matrix.get('rows', []))}, "
            f"structure_sections={len(structure_sections)}"
        )

        if not document_text:
            return SkillResult(success=False, error="招标文件内容为空")

        scoring_items = scoring_matrix.get("rows", [])
        scoring_text = ""
        if scoring_items:
            scoring_text = "\n".join(
                f"- [{item.get('category', '')}] {item.get('item', '')} "
                f"({item.get('score', 0)}分)"
                for item in scoring_items
            )

        try:
            result = await self._step_by_step_generate(
                ctx, document_text, scoring_text, scoring_items, mode, structure_hint
            )
            outline = result.data.get("outline", {})
            validation_error = _validate_outline(outline)
            if validation_error:
                logger.warning(f"[OutlineGenSkill] 分步生成结果校验失败: {validation_error}")
                chapters = outline.get("chapters", [])
                chapters_with_children = sum(1 for c in chapters if c.get("children"))
                if chapters_with_children > 0 and len(chapters) >= 5:
                    logger.info(f"[OutlineGenSkill] 补充缺失子目录({chapters_with_children}/{len(chapters)}已有子目录)")
                    for ch in chapters:
                        if not ch.get("children"):
                            ch["children"] = _generate_default_sub_chapters(ch.get("title", ""), ch.get("id", ""))
                    outline["chapters"] = chapters
                    result = SkillResult(success=True, data={"outline": outline, "mode": mode})
                else:
                    logger.warning("[OutlineGenSkill] 有效章节过少，降级到一次性生成")
                    result = await self._one_shot_generate(ctx, document_text, scoring_text, mode, structure_hint)
            return result
        except Exception as e:
            logger.warning(f"[OutlineGenSkill] 分步生成异常: {e}，降级到一次性生成")
            return await self._one_shot_generate(ctx, document_text, scoring_text, mode, structure_hint)

    async def _generate_children_for_chapter(
        self, ctx: SkillContext, i: int, chapter: dict, text: str, scoring_text: str
    ) -> tuple[int, dict, list]:
        """为单个一级章节生成二三级子目录（用于并行调用）。"""
        chapter_title = chapter.get("title", f"章节{i+1}")
        chapter_desc = chapter.get("description", "")

        child_messages = _build_step2_messages(chapter_title, chapter_desc, text, scoring_text)

        try:
            logger.info(f"[OutlineGenSkill] Step2: 生成 '{chapter_title}' 的子目录")
            child_result = await asyncio.wait_for(
                ctx.llm.collect_json(
                    messages=child_messages,
                    temperature=0.7,
                    max_tokens=self.STEP2_MAX_TOKENS,
                ),
                timeout=STEP2_TIMEOUT,
            )
            children = child_result.get("children", [])
            if not isinstance(children, list):
                children = []
        except asyncio.TimeoutError:
            logger.warning(f"[OutlineGenSkill] Step2: '{chapter_title}' 超时({STEP2_TIMEOUT}s)，跳过")
            children = []
        except Exception as e:
            logger.warning(f"[OutlineGenSkill] Step2: '{chapter_title}' 失败: {e}")
            children = []

        fixed_children = []
        for j, child in enumerate(children):
            if not isinstance(child, dict):
                continue
            child_title = str(child.get("title", "")).strip()
            if not child_title:
                continue
            child_id = f"{i+1}.{j+1}"
            sub_children = child.get("children", [])
            if not isinstance(sub_children, list):
                sub_children = []
            fixed_sub = []
            for k, sub in enumerate(sub_children):
                if isinstance(sub, dict):
                    sub_title = str(sub.get("title", "")).strip()
                    if sub_title:
                        fixed_sub.append({"id": f"{child_id}.{k+1}", "title": sub_title, "level": 3, "children": []})
            fixed_children.append({"id": child_id, "title": child_title, "level": 2, "children": fixed_sub})

        full_chapter = {
            "id": str(i + 1),
            "title": chapter_title,
            "level": 1,
            "children": fixed_children,
        }
        logger.info(f"[OutlineGenSkill] Step2: '{chapter_title}' → {len(fixed_children)}个二级节")
        return (i, full_chapter, fixed_children)

    async def _step_by_step_generate(
        self, ctx: SkillContext, text: str, scoring_text: str,
        scoring_items: list, mode: str, structure_hint: str = ""
    ) -> SkillResult:
        t0 = time.monotonic()

        # Step 1: 生成一级目录
        messages = _build_step1_messages(text, scoring_text, mode, structure_hint)
        logger.info(f"[OutlineGenSkill] Step1: 生成一级目录, mode={mode}")

        step1_result = await ctx.llm.collect_json(messages=messages, temperature=0.7)
        top_chapters = step1_result.get("chapters", [])
        if not isinstance(top_chapters, list) or not top_chapters:
            raise ValueError("一级目录生成结果为空")

        logger.info(f"[OutlineGenSkill] Step1完成: {len(top_chapters)}个一级目录, 耗时={time.monotonic()-t0:.1f}s")

        # Step 2: 并行生成二三级子目录（核心优化）
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        async def _limited_generate(i, chapter):
            async with semaphore:
                return await self._generate_children_for_chapter(ctx, i, chapter, text, scoring_text)

        tasks = []
        for i, chapter in enumerate(top_chapters):
            if isinstance(chapter, dict):
                tasks.append(_limited_generate(i, chapter))

        logger.info(f"[OutlineGenSkill] Step2: 并行生成 {len(tasks)} 个章节的子目录, 并发数={MAX_CONCURRENT}")
        step2_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 按索引排序组装结果
        full_chapters = [None] * len(top_chapters)
        for r in step2_results:
            if isinstance(r, Exception):
                logger.warning(f"[OutlineGenSkill] Step2 某章节生成异常: {r}")
                continue
            idx, full_chapter, _ = r
            full_chapters[idx] = full_chapter

        # 填充缺失的章节（生成失败的）
        for i, chapter in enumerate(top_chapters):
            if full_chapters[i] is None:
                if isinstance(chapter, dict):
                    full_chapters[i] = {
                        "id": str(i + 1),
                        "title": chapter.get("title", f"章节{i+1}"),
                        "level": 1,
                        "children": [],
                    }

        elapsed = time.monotonic() - t0
        total_nodes = sum(
            1 + len(c.get("children", []))
            + sum(len(sc.get("children", [])) for sc in c.get("children", []))
            for c in full_chapters if c
        )
        logger.info(f"[OutlineGenSkill] 分步生成完成: {len(full_chapters)}个一级目录, 共{total_nodes}个节点, 耗时={elapsed:.1f}s")

        outline = {"chapters": full_chapters}

        if mode == "aligned" and scoring_items:
            score_mapping = {}
            for item in scoring_items:
                item_name = item.get("item", item.get("category", ""))
                if not item_name:
                    continue
                item_tokens = _tokenize_chinese(item_name)
                best_id = ""
                best_score = 0
                for ch in full_chapters:
                    if not ch:
                        continue
                    ch_title = ch["title"]
                    ch_tokens = _tokenize_chinese(ch_title)
                    # 词级匹配：计算 item 特征词在章节标题词集中的命中率
                    if not item_tokens:
                        continue
                    hits = len(item_tokens & ch_tokens)
                    # 归一化得分 = 命中词数 / item总词数
                    score = hits / max(len(item_tokens), 1)
                    # 额外加分：如果 item_name 整体出现在标题中
                    if item_name in ch_title or ch_title in item_name:
                        score += 2.0
                    if score > best_score:
                        best_score = score
                        best_id = ch["id"]
                # 仅当匹配置信度足够时才建立映射
                if best_id and best_score >= 0.3:
                    score_mapping[item_name] = best_id
            outline["score_mapping"] = score_mapping

        return SkillResult(success=True, data={"outline": outline, "mode": mode})

    async def _one_shot_generate(
        self, ctx: SkillContext, text: str, scoring_text: str, mode: str, structure_hint: str = ""
    ) -> SkillResult:
        logger.info("[OutlineGenSkill] 使用一次性生成模式")
        messages = _build_one_shot_messages(text, scoring_text, mode, structure_hint)
        result = await ctx.llm.collect_json(messages=messages, temperature=0.7, max_tokens=16384)
        fixed = _fix_outline(result)
        if not fixed.get("chapters"):
            logger.warning("[OutlineGenSkill] 一次性生成结果为空，尝试精简模式重新生成")
            shorter_text = text[:ONE_SHOT_RETRY_TEXT_LIMIT] if len(text) > ONE_SHOT_RETRY_TEXT_LIMIT else text
            shorter_scoring = scoring_text[:1000] if len(scoring_text) > 1000 else scoring_text
            messages = _build_one_shot_messages(shorter_text, shorter_scoring, mode, structure_hint)
            result = await ctx.llm.collect_json(messages=messages, temperature=0.7, max_tokens=16384)
            fixed = _fix_outline(result)
        return SkillResult(success=True, data={"outline": fixed, "mode": mode})
