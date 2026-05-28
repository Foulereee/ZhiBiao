"""大纲生成 Skill v5.1.0 — 参考 OpenBidKit 的完整工作流。

核心改进：
1. 分步生成：一级目录 → 逐个二三级子目录 → 合并（7B模型友好）
2. 自动降级：一次性生成失败 → 自动切换分步生成
3. 结果校验：生成后校验大纲结构完整性
4. Prompt 优化：参考 ai_bidding 的详细规范和 OpenBidKit 的结构化消息
5. max_tokens 控制：Step2 限制 2048 tokens 防止7B模型过度展开
"""

from __future__ import annotations

import json
import logging
import re
import time

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────

def _fix_outline_node(node: dict, parent_id: str = "", seq: int = 0, level: int = 1) -> dict:
    """Fix and normalize a single outline node."""
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

    return {
        "id": node_id,
        "title": title,
        "level": node_level,
        "children": fixed_children,
    }


def _fix_outline(data: dict) -> dict:
    """Fix and normalize the entire outline structure."""
    if not isinstance(data, dict):
        logger.warning(f"[OutlineGenSkill] _fix_outline: data不是dict, type={type(data)}")
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
                "id": str(i + 1),
                "title": chapter.strip() or f"章节 {i+1}",
                "level": 1,
                "children": [],
            })

    result = {"chapters": fixed_chapters}

    score_mapping = data.get("score_mapping", {})
    if score_mapping and isinstance(score_mapping, dict):
        result["score_mapping"] = score_mapping

    return result


def _validate_outline(outline: dict) -> str | None:
    """校验大纲结构完整性，返回错误信息或 None。"""
    chapters = outline.get("chapters", [])
    if not chapters:
        return "大纲章节为空"

    # 检查一级目录数量
    if len(chapters) < 5:
        return f"一级目录数量过少({len(chapters)}个)，至少需要5个"

    # 检查二级目录覆盖率
    chapters_with_children = sum(1 for c in chapters if c.get("children"))
    if chapters_with_children < len(chapters) * 0.5:
        return f"大部分一级目录缺少二级子目录({chapters_with_children}/{len(chapters)})"

    return None


# ─────────────────────────────────────────────
# Prompt 模板（参考 OpenBidKit 的结构化消息方式）
# ─────────────────────────────────────────────

def _build_step1_messages(text: str, scoring_text: str, mode: str) -> list[dict]:
    """构建 Step1 一级目录生成的消息列表。"""
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
            "6. 返回标准 JSON 格式，只返回 JSON，不要输出任何其他内容。\n\n"
            "JSON 格式要求：\n"
            '{"chapters": [{"title": "章节标题", "description": "本章内容概述(20字以上)"}]}'
        )
        user_msgs = [
            {"role": "user", "content": f"招标文件摘要：\n{text[:8000]}"},
            {"role": "user", "content": f"评分标准：\n{scoring_text}"},
            {"role": "user", "content": "请根据以上招标文件和评分标准，生成投标文件的一级目录结构。"},
        ]
    else:
        system_msg = (
            "你是一个专业的标书编写专家。根据提供的招标文件内容，"
            "生成投标文件的一级目录结构。\n\n"
            "要求：\n"
            "1. 一级目录名称要专业、准确，符合投标文件规范。\n"
            "2. 一般包含8-15个一级章节。\n"
            "3. 必须包含：投标函、资格审查、技术方案、商务报价等基本章节。\n"
            "4. 返回标准 JSON 格式，只返回 JSON，不要输出任何其他内容。\n\n"
            "JSON 格式要求：\n"
            '{"chapters": [{"title": "章节标题", "description": "本章内容概述(20字以上)"}]}'
        )
        user_msgs = [
            {"role": "user", "content": f"招标文件摘要：\n{text[:8000]}"},
            {"role": "user", "content": "请根据以上招标文件内容，生成投标文件的一级目录结构。"},
        ]

    return [{"role": "system", "content": system_msg}] + user_msgs


def _build_step2_messages(
    chapter_title: str, chapter_desc: str, text: str, scoring_text: str
) -> list[dict]:
    """构建 Step2 二三级子目录生成的消息列表。

    关键设计：Prompt 非常简洁，只要求标题，不要求描述，
    防止7B模型过度展开导致输出过长。
    """
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
        user_content += f"\n说明：{chapter_desc[:100]}"

    user_msgs = [
        {"role": "user", "content": user_content},
    ]
    if scoring_text:
        user_msgs.append(
            {"role": "user", "content": f"相关评分标准：\n{scoring_text[:500]}"}
        )
    user_msgs.append(
        {"role": "user", "content": "请生成该一级章节下的二三级子目录。"}
    )

    return [{"role": "system", "content": system_msg}] + user_msgs


def _build_one_shot_messages(text: str, scoring_text: str, mode: str) -> list[dict]:
    """构建一次性生成完整大纲的消息列表。"""
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

    user_msgs = [{"role": "user", "content": f"招标文件摘要：\n{text[:6000]}"}]
    if scoring_text and mode == "aligned":
        user_msgs.append({"role": "user", "content": f"评分标准：\n{scoring_text}"})
    user_msgs.append(
        {"role": "user", "content": "请生成完整的三级目录大纲，确保覆盖所有评分要点。"}
    )

    return [{"role": "system", "content": system_msg}] + user_msgs


# ─────────────────────────────────────────────
# 主 Skill 类
# ─────────────────────────────────────────────

class OutlineGenSkill(Skill):
    name = "outline_gen"
    description = "大纲生成(分步模式+自动降级)"
    category = "generate"
    version = "5.1.0"
    triggers = ["大纲", "目录", "提纲"]

    # Step2 的 max_tokens 限制，防止7B模型过度展开
    STEP2_MAX_TOKENS = 2048

    async def execute(self, ctx: SkillContext) -> SkillResult:
        mode = ctx.parameters.get("mode", "aligned")
        document_text = ctx.parameters.get("document_text", "")
        scoring_matrix = ctx.parameters.get("scoring_matrix", {})

        logger.info(
            f"[OutlineGenSkill] mode={mode}, 文档长度={len(document_text)}字符, "
            f"scoring_matrix_rows={len(scoring_matrix.get('rows', []))}"
        )

        if not document_text:
            return SkillResult(success=False, error="招标文件内容为空")

        # 准备评分标准文本和评分项列表
        scoring_items = scoring_matrix.get("rows", [])
        scoring_text = ""
        if scoring_items:
            scoring_text = "\n".join(
                f"- [{item.get('category', '')}] {item.get('item', '')} "
                f"({item.get('score', 0)}分)"
                for item in scoring_items
            )

        # 参考 OpenBidKit 的 auto 模式：先尝试分步生成，失败则降级
        try:
            result = await self._step_by_step_generate(
                ctx, document_text, scoring_text, scoring_items, mode
            )
            # 校验结果
            outline = result.data.get("outline", {})
            validation_error = _validate_outline(outline)
            if validation_error:
                logger.warning(
                    f"[OutlineGenSkill] 分步生成结果校验失败: {validation_error}，"
                    f"降级到一次性生成"
                )
                result = await self._one_shot_generate(ctx, document_text, scoring_text, mode)
            return result
        except Exception as e:
            logger.warning(f"[OutlineGenSkill] 分步生成异常: {e}，降级到一次性生成")
            return await self._one_shot_generate(ctx, document_text, scoring_text, mode)

    async def _step_by_step_generate(
        self,
        ctx: SkillContext,
        text: str,
        scoring_text: str,
        scoring_items: list,
        mode: str,
    ) -> SkillResult:
        """分步生成大纲：先一级目录 → 再逐个二三级子目录 → 合并。"""
        t0 = time.monotonic()

        # ── Step 1: 生成一级目录 ──
        messages = _build_step1_messages(text, scoring_text, mode)
        logger.info(f"[OutlineGenSkill] Step1: 生成一级目录, mode={mode}")

        step1_result = await ctx.llm.collect_json(messages=messages, temperature=0.7)

        top_chapters = step1_result.get("chapters", [])
        if not isinstance(top_chapters, list) or not top_chapters:
            logger.warning("[OutlineGenSkill] Step1: 一级目录为空")
            raise ValueError("一级目录生成结果为空")

        logger.info(
            f"[OutlineGenSkill] Step1完成: {len(top_chapters)}个一级目录, "
            f"耗时={time.monotonic()-t0:.1f}s"
        )

        # ── Step 2: 逐个一级目录生成二三级子目录 ──
        full_chapters = []
        for i, chapter in enumerate(top_chapters):
            if not isinstance(chapter, dict):
                continue
            chapter_title = chapter.get("title", f"章节{i+1}")
            chapter_desc = chapter.get("description", "")

            child_messages = _build_step2_messages(
                chapter_title, chapter_desc, text, scoring_text
            )

            try:
                logger.info(f"[OutlineGenSkill] Step2: 生成 '{chapter_title}' 的子目录")
                # 关键：限制 max_tokens 防止7B模型过度展开
                child_result = await ctx.llm.collect_json(
                    messages=child_messages,
                    temperature=0.7,
                    max_tokens=self.STEP2_MAX_TOKENS,
                )
                children = child_result.get("children", [])
                if not isinstance(children, list):
                    children = []
            except Exception as e:
                logger.warning(
                    f"[OutlineGenSkill] Step2: '{chapter_title}' 子目录生成失败: {e}"
                )
                children = []

            # 构建完整的一级章节节点
            fixed_children = []
            for j, child in enumerate(children):
                if not isinstance(child, dict):
                    continue
                child_title = str(child.get("title", "")).strip()
                if not child_title:
                    continue
                child_id = f"{i+1}.{j+1}"

                # 三级小节
                sub_children = child.get("children", [])
                if not isinstance(sub_children, list):
                    sub_children = []
                fixed_sub = []
                for k, sub in enumerate(sub_children):
                    if isinstance(sub, dict):
                        sub_title = str(sub.get("title", "")).strip()
                        if sub_title:
                            fixed_sub.append({
                                "id": f"{child_id}.{k+1}",
                                "title": sub_title,
                                "level": 3,
                                "children": [],
                            })

                fixed_children.append({
                    "id": child_id,
                    "title": child_title,
                    "level": 2,
                    "children": fixed_sub,
                })

            full_chapters.append({
                "id": str(i + 1),
                "title": chapter_title,
                "level": 1,
                "children": fixed_children,
            })

            logger.info(
                f"[OutlineGenSkill] Step2: '{chapter_title}' → "
                f"{len(fixed_children)}个二级节"
            )

        elapsed = time.monotonic() - t0
        total_nodes = sum(
            1 + len(c.get("children", []))
            + sum(len(sc.get("children", [])) for sc in c.get("children", []))
            for c in full_chapters
        )
        logger.info(
            f"[OutlineGenSkill] 分步生成完成: {len(full_chapters)}个一级目录, "
            f"共{total_nodes}个节点, 耗时={elapsed:.1f}s"
        )

        outline = {"chapters": full_chapters}

        # 构建 score_mapping（aligned 模式）
        if mode == "aligned" and scoring_items:
            score_mapping = {}
            for item in scoring_items:
                item_name = item.get("item", item.get("category", ""))
                best_id = ""
                best_score = 0
                for ch in full_chapters:
                    ch_title = ch["title"]
                    overlap = sum(1 for c in item_name if c in ch_title)
                    if overlap > best_score:
                        best_score = overlap
                        best_id = ch["id"]
                if best_id:
                    score_mapping[item_name] = best_id
            outline["score_mapping"] = score_mapping

        return SkillResult(success=True, data={"outline": outline, "mode": mode})

    async def _one_shot_generate(
        self, ctx: SkillContext, text: str, scoring_text: str, mode: str
    ) -> SkillResult:
        """一次性生成完整大纲（降级方案）。"""
        logger.info("[OutlineGenSkill] 使用一次性生成模式")

        messages = _build_one_shot_messages(text, scoring_text, mode)
        result = await ctx.llm.collect_json(messages=messages, temperature=0.7)
        fixed = _fix_outline(result)

        return SkillResult(success=True, data={"outline": fixed, "mode": mode})
