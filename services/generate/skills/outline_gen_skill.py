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

# 每页约 800 字(用户实测),结构模板的目标页数换算成字数喂给模型
CHARS_PER_PAGE = 800

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
            # 统一口径:每页约 800 字(用户实测导出 docx 每页约 800 字),
            # 不再让模型按"页"思考,否则页数口径前后不一致。
            extras.append(f"目标约{int(page) * CHARS_PER_PAGE}字")
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
    # 【必须保留 description】它是全书唯一一处"本节到底写什么"的说明：
    #   ① 正文链路用它渲染【当前章节大纲】与【同级章节（请避免内容重复）】
    #      （generate.py 的 _node_line / _describe_node_tree）；
    #   ② 编排阶段（content_plan_skill.format_outline_for_plan）用它判断各节
    #      分工与边界 —— 没有它，编排看到的完整目录只有一串标题，写出来的
    #      writing_focus 只能靠标题猜。
    # 以前这里只返回 id/title/level/children，description 被就地丢掉，加上
    # _renumber_outline 也不保留，导致全链路恒空：实测 213 章的"章节上下文"
    # 中位只有 172 字符。对标易标：目录节点必带 description
    # （outlineGenerationTaskV2.cjs:653「description 是目录说明」，schema 必填）。
    fixed = {
        "id": node_id, "title": title, "level": node_level,
        "children": fixed_children,
    }
    _desc = str(node.get("description") or node.get("describe") or "").strip()
    if _desc:
        fixed["description"] = _desc
    # points 是"被合并/被裁掉的更深层标题"，正文提示词当写作要点用，不能丢
    if isinstance(node.get("points"), list) and node["points"]:
        fixed["points"] = node["points"]
    return fixed


def _renumber_outline(items: list, parent: str = "") -> list:
    results = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        new_id = f"{parent}.{idx + 1}" if parent else str(idx + 1)
        entry = {"id": new_id, "title": item.get("title", ""), "level": item.get("level", 1)}
        # description（与历史上的 describe）必须随重编号一起带过去，否则前面
        # _fix_outline_node 刚保住的目录说明会在这里再次丢失。
        _desc = str(item.get("description") or item.get("describe") or "").strip()
        if _desc:
            entry["description"] = _desc
        if item.get("content"):
            entry["content"] = item["content"]
        # points 是"被合并掉的更深层标题"，供正文提示词当写作要点用
        if item.get("points"):
            entry["points"] = item["points"]
        children = item.get("children", [])
        if children and isinstance(children, list):
            entry["children"] = _renumber_outline(children, new_id)
        results.append(entry)
    return results


# 投标文件目录的最大层级。
# 实测导出的标书出现了 1.1.1.1 / 1.1.1.1.1（Heading 5 共 323 段），
# 原因是 Step2"为每个一级章节生成二三级子目录"时模型会继续往下套娃，
# 而生成后的归一化只做了编号重排、没有深度上限，同名覆盖也不管。
# 国内投标文件的通行深度是"章/节/条"三级，更深的内容应该写成正文段落。
MAX_OUTLINE_DEPTH = 3

# 子标题相对父标题只多了这些词时，视为同一个章节（重复展开）
_DUP_SUFFIXES = ("正文", "说明", "概述", "详细说明", "具体内容", "及附件", "及相关材料",
                 "如适用", "（如适用）", "(如适用)")


def _norm_title(title: str) -> str:
    t = str(title or "")
    t = re.sub(r"[\s\u3000]", "", t)
    return re.sub(r"[()（）【】\[\]:：、,，.。\-—_/]", "", t)


def _is_dup_child(parent_title: str, child_title: str) -> bool:
    """父子标题语义重复判定（父:投标函 / 子:投标函正文；父:信用证明 / 子:信用证明）。"""
    p, c = _norm_title(parent_title), _norm_title(child_title)
    if not p or not c:
        return False
    if p == c:
        return True
    return any(c == _norm_title(p + suf) for suf in _DUP_SUFFIXES)


def _dedup_outline(nodes: list) -> list:
    """去掉"父子同名"的冗余节点，把子节点的子节点提升上来。

    实例（实测 端头…docx）：
        1    投标函及商务承诺
        1.1  投标函
        1.1.1  投标函正文
        1.1.1.1  投标函
        1.1.1.1.1  投标函正文      ← 同一份材料套娃了四层
    归一化后只保留 1 / 1.1，后面的层级被折叠。
    """
    out: list[dict] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        children = _dedup_outline(node.get("children") or [])
        promoted: list[dict] = []
        for child in children:
            if _is_dup_child(node.get("title", ""), child.get("title", "")):
                promoted.extend(_dedup_outline(child.get("children") or []))
            else:
                promoted.append(child)
        merged = dict(node)
        merged["children"] = promoted
        out.append(merged)

    # 同级同名去重：实测一级目录里出现 3 个"法定代表人身份证明"、2 个"开标一览表"，
    # 会生成 5~6 份同样的材料章节。保留第一个，把后来的合并成写作要点。
    deduped: list[dict] = []
    seen: dict[str, dict] = {}
    for node in out:
        key = _norm_title(node.get("title", ""))
        if not key:
            deduped.append(node)
            continue
        if key in seen:
            keeper = seen[key]
            extra = list(node.get("points") or [])
            for ch in node.get("children") or []:
                t = str(ch.get("title") or "").strip()
                if t and t not in extra:
                    extra.append(t)
            if extra:
                points = list(keeper.get("points") or [])
                for t in extra:
                    if t not in points:
                        points.append(t)
                keeper["points"] = points
            continue
        seen[key] = node
        deduped.append(node)
    return deduped


def _dedup_until_stable(nodes: list, max_rounds: int = 6) -> list:
    """反复去重直到不再变化。

    为什么要迭代：一次去重会把"重复子节点"提升上来，提升后的节点可能和它的
    新父亲又构成重复。实例（实测 端头…docx 的套娃链）：
        1 投标函及商务承诺 → 1.1 投标函 → 1.1.1 投标函正文
        → 1.1.1.1 投标函 → 1.1.1.1.1 投标函正文
    单轮去重只吃掉中间两层，剩下的"投标函"会顶替"投标函正文"的位置，与 1.1
    再次同名。实测单轮后仍是 `1 投标函及商务承诺 → 1.1 投标函 → 1.1.1 投标函`。
    """
    prev = None
    cur = nodes
    for _ in range(max_rounds):
        cur = _dedup_outline(cur)
        sig = json.dumps(cur, ensure_ascii=False, sort_keys=True)
        if sig == prev:
            break
        prev = sig
    return cur


def _prune_outline_depth(nodes: list, depth: int = 1) -> list:
    """把超过 MAX_OUTLINE_DEPTH 的层级裁掉，并把被裁掉的标题收进父节点的 points。

    不直接丢弃内容：更深的标题会作为"写作要点"传给正文生成，让那一章把
    这些点写进正文段落里，而不是变成四五级标题。
    """
    out: list[dict] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        children = node.get("children") or []
        if depth >= MAX_OUTLINE_DEPTH:
            collected: list[str] = []

            def _collect(ns: list) -> None:
                for c in ns or []:
                    if not isinstance(c, dict):
                        continue
                    t = str(c.get("title") or "").strip()
                    if t and t not in collected:
                        collected.append(t)
                    _collect(c.get("children") or [])

            _collect(children)
            pruned = dict(node)
            pruned["children"] = []
            if collected:
                existing = node.get("points")
                points = list(existing) if isinstance(existing, list) else []
                for t in collected:
                    if t not in points:
                        points.append(t)
                pruned["points"] = points
            out.append(pruned)
            continue
        pruned = dict(node)
        pruned["children"] = _prune_outline_depth(children, depth + 1)
        out.append(pruned)
    return out


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
    # 顺序很重要：先去重（同名父子会把层级撑深，且需迭代到不动点），
    # 再裁深度，最后统一重编号。
    fixed_chapters = _dedup_until_stable(fixed_chapters)
    fixed_chapters = _prune_outline_depth(fixed_chapters)
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

    # 深度与重名只告警、不作为校验失败：_fix_outline 里有确定性的
    # _dedup_outline / _prune_outline_depth 会处理掉，这里再报错只会
    # 触发昂贵的"降级到一次性生成"，反而更差。
    def _depth(nodes: list, d: int = 1) -> int:
        best = d
        for n in nodes or []:
            if isinstance(n, dict) and n.get("children"):
                best = max(best, _depth(n["children"], d + 1))
        return best

    real_depth = _depth(chapters)
    if real_depth > MAX_OUTLINE_DEPTH:
        logger.warning(
            "[OutlineGenSkill] 大纲层级过深(%s 级，上限 %s)，将裁到 %s 级并把更深标题转为写作要点",
            real_depth, MAX_OUTLINE_DEPTH, MAX_OUTLINE_DEPTH,
        )
    dup_titles = [t for t, n in _count_titles(chapters).items() if n > 1]
    if dup_titles:
        logger.warning("[OutlineGenSkill] 存在同级重名目录 %s 组，将自动合并", len(dup_titles))
    return None


def _count_titles(nodes: list) -> dict[str, int]:
    """统计各层级标题出现次数（只用于告警）。"""
    counts: dict[str, int] = {}
    stack = list(nodes or [])
    while stack:
        n = stack.pop()
        if not isinstance(n, dict):
            continue
        key = _norm_title(n.get("title", ""))
        if key:
            counts[key] = counts.get(key, 0) + 1
        stack.extend(n.get("children") or [])
    return counts


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


# 评分项 → 章节 的匹配置信度下限。
# 实测：真实评分项「企业类似业绩」对章节「企业信誉与类似业绩」=0.67、
# 「履约能力与财务状况」对「财务状况与社保纳税证明」=0.44，
# 而泛化词「技术部分」对任何章节都 <=0.25 —— 0.30 能干净地分开这两类。
SCORE_MATCH_THRESHOLD = 0.30


def _lcs_length(a: str, b: str) -> int:
    """最长公共子串长度（必须连续）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _char_dice(a: str, b: str) -> float:
    """字符二元 Dice 系数：中文里对「企业信用」/「企业信誉」这类近义词最敏感。"""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return 2 * len(sa & sb) / (len(sa) + len(sb))


def score_item_similarity(item_name: str, title: str) -> float:
    """评分项名 与 章节标题 的相似度（0~1）。

    三种信号取最大值，专门解决中文没有词边界、评分项措辞与章节标题
    永远不字面相等的问题（旧实现用 `in` 子串匹配 + 按空格 split，
    中文下恒不命中，覆盖率因此永远是 0）。
    """
    item = re.sub(r"\s+", "", str(item_name or ""))
    ttl = re.sub(r"\s+", "", str(title or ""))
    if not item or not ttl:
        return 0.0
    # 1) 字面包含：最可靠
    if item in ttl or ttl in item:
        return 1.0
    # 2) 最长公共子串 占 评分项 的比例
    lcs_ratio = _lcs_length(item, ttl) / max(len(item), 1)
    # 3) 2-4 字特征词命中率
    item_tokens = _tokenize_chinese(item)
    ttl_tokens = _tokenize_chinese(ttl)
    overlap = len(item_tokens & ttl_tokens) / max(len(item_tokens), 1) if item_tokens else 0.0
    # 4) 字符 Dice，兜住近义词
    return max(lcs_ratio, overlap, _char_dice(item, ttl))


def best_matching_title(item_name: str, titles: list[str]) -> tuple[str, float]:
    """在一批标题里找与评分项最贴合的一个，返回 (标题, 相似度)。"""
    best_title, best_score = "", 0.0
    for title in titles or []:
        score = score_item_similarity(item_name, title)
        if score > best_score:
            best_score, best_title = score, title
    return best_title, best_score


def match_score_items_to_chapters(scoring_items: list[dict], chapters: list[dict]) -> dict:
    """把评分项映射到最贴合的一级章节，返回 {评分项名: 章节id}。

    低于 SCORE_MATCH_THRESHOLD 的项**故意不映射**（宁缺毋滥）：
    错误的映射会让正文去写不相干的内容，比不映射更糟。
    """
    mapping: dict[str, str] = {}
    usable = [
        c for c in (chapters or [])
        if isinstance(c, dict) and c.get("title")
    ]
    if not usable:
        return mapping

    for item in scoring_items or []:
        if not isinstance(item, dict):
            continue
        item_name = item.get("item") or item.get("name") or item.get("category") or ""
        if not item_name:
            continue
        best_id, best_score = "", 0.0
        for ch in usable:
            score = score_item_similarity(item_name, ch.get("title", ""))
            if score > best_score:
                best_score, best_id = score, str(ch.get("id", ""))
        if best_id and best_score >= SCORE_MATCH_THRESHOLD:
            mapping[str(item_name)] = best_id
    return mapping


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
            "5. 章节组成必须严格服从下方【生成范围要求】；若未给出生成范围要求，"
            "才按完整投标文件处理，包含投标函、资格审查、技术方案、商务报价等基本章节。\n"
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
            "3. 章节组成必须严格服从下方【生成范围要求】；若未给出生成范围要求，"
            "才按完整投标文件处理，包含投标函、资格审查、技术方案、商务报价等基本章节。\n"
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
        if mode == "aligned":
            # 用户选了"对齐评分项模式",但解析结果里没有评分矩阵(rows 为空)。
            # 此时提示词里一个具体评分项都没有,大纲只是"看起来"对齐了;
            # 所以明确要求模型自己先从招标文件里把评分项提取出来再对齐。
            logger.warning(
                "[OutlineGenSkill] mode=aligned 但 scoring_matrix 无 rows:"
                "提示词改为要求模型自行从招标文件中提取评分项"
            )
            user_msgs.append({
                "role": "user",
                "content": (
                    "【对齐评分项模式】请先从上面的招标文件中逐条提取评分办法/评分标准里的"
                    "评分项(含分值),列成清单;再让一级目录逐条覆盖这些评分项,"
                    "一级目录名称尽量与评分项名称一致。"
                ),
            })
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

        # 生成范围硬约束（完整投标文件 / 技术标独立成册 / 商务标独立成册）。
        # 放在最前面，因为它与"必须包含投标函、资格审查…"这类默认要求冲突时
        # 必须以它为准；没有它，用户选了技术标也会生成出完整投标文件。
        _scope_req = str(ctx.parameters.get("scope_requirement") or "").strip()
        if _scope_req:
            structure_hint = (f"{_scope_req}\n\n{structure_hint}").strip()
            logger.info("[OutlineGenSkill] 已注入生成范围约束 %d 字", len(_scope_req))

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
                        sub_node = {
                            "id": f"{child_id}.{k+1}", "title": sub_title,
                            "level": 3, "children": [],
                        }
                        # 三级小节的 description 同样要留着 —— 它是正文里
                        # 【本章任务】"结构要求"之外唯一的范围依据
                        _sd = str(sub.get("description") or sub.get("describe") or "").strip()
                        if _sd:
                            sub_node["description"] = _sd
                        fixed_sub.append(sub_node)
            child_node = {
                "id": child_id, "title": child_title, "level": 2,
                "children": fixed_sub,
            }
            _cd = str(child.get("description") or child.get("describe") or "").strip()
            if _cd:
                child_node["description"] = _cd
            fixed_children.append(child_node)

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
            # 统一走 score_item_similarity（LCS + 特征词 + 字符Dice），
            # 旧的 "词命中率 + 0.3 阈值" 对中文实际只有字面重合才生效，
            # 导致 score_mapping 常为空 → 正文生成完全收不到评分项提示。
            score_mapping = match_score_items_to_chapters(scoring_items, full_chapters)
            outline["score_mapping"] = score_mapping
            if not score_mapping:
                logger.warning(
                    "[OutlineGenSkill] score_mapping 为空: 评分项与一级章节标题无一达到 "
                    f"阈值 {SCORE_MATCH_THRESHOLD}，正文将不会收到评分项提示"
                )
            else:
                logger.info(f"[OutlineGenSkill] score_mapping 命中 {len(score_mapping)}/{len(scoring_items)} 项")

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
