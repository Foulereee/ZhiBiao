from __future__ import annotations

import json
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 加载外部规则配置文件
_RULES_FILE = Path(__file__).parent / "content_cleaner_rules.json"
_LOADED_RULES: dict = {}


def _load_rules() -> dict:
    """从 JSON 配置文件加载修复规则。带缓存。"""
    global _LOADED_RULES
    if _LOADED_RULES:
        return _LOADED_RULES
    try:
        if _RULES_FILE.exists():
            with open(_RULES_FILE, "r", encoding="utf-8") as f:
                _LOADED_RULES = json.load(f)
            logger.info(f"[content_cleaner] 已加载修复规则: {_RULES_FILE.name}")
        else:
            logger.warning(f"[content_cleaner] 规则文件不存在: {_RULES_FILE}")
            _LOADED_RULES = {}
    except Exception as e:
        logger.error(f"[content_cleaner] 加载规则失败: {e}")
        _LOADED_RULES = {}
    return _LOADED_RULES


# --- 规则引擎 ---

class Rule:
    """单条文本修复规则。

    - is_regex=True  → 走 re.sub（编译失败时降级为纯文本替换）
    - is_regex=False → 走 str.replace
    - multiline=True → re.MULTILINE 标志
    """

    __slots__ = ("name", "pattern", "replacement", "multiline", "is_regex")

    def __init__(
        self,
        name: str,
        pattern: str,
        replacement: str,
        multiline: bool = False,
        is_regex: bool = True,
    ):
        self.name = name
        self.pattern = pattern
        self.replacement = replacement
        self.multiline = multiline
        self.is_regex = is_regex

    def apply(self, text: str) -> str:
        if not self.is_regex:
            return text.replace(self.pattern, self.replacement)
        flags = re.MULTILINE if self.multiline else 0
        try:
            return re.sub(self.pattern, self.replacement, text, flags=flags)
        except re.error as e:
            logger.warning(
                f"[content_cleaner] 规则 {self.name} 正则错误: {e} → 降级为纯文本替换"
            )
            return text.replace(self.pattern, self.replacement)


def apply_rules(text: str, rules: list[Rule]) -> str:
    """按序应用一组规则。空规则列表直接返回原文本。"""
    for rule in rules:
        text = rule.apply(text)
    return text


# --- 内联函数：直接走 re.sub 的（保持原样以减少改动） ---

def _remove_bom_and_control_chars(text: str) -> str:
    text = text.replace('\ufeff', '')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'[\u200b-\u200f\u202a-\u202e]', '', text)
    return text


def _remove_code_fences(text: str) -> str:
    text = re.sub(r'^```\w*\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    return text


def _fix_br_tags(text: str) -> str:
    text = re.sub(r'<br\s*/?>\s*', '  \n', text)
    return text


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r' {4,}', '   ', text)
    return text


def _remove_garbled_lines(text: str) -> str:
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if re.match(r'^[\u4e00-\u9fff]z+$', stripped):
            continue
        if re.match(r'^z+$', stripped):
            continue
        if re.match(r'^[\u4e00-\u9fff]?z?$', stripped) and len(stripped) <= 2:
            continue
        if re.match(r'^\d+$', stripped) and len(stripped) <= 2:
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


# --- 规则引擎重构的 5 个最混乱函数 ---

# 1. 孤立 z 字符清理（中文字符间混入的 z 噪声）
_ORPHAN_Z_RULES: list[Rule] = [
    Rule("orphan_z_cjk_cjk",
         r'(?<=[\u4e00-\u9fff])z+(?=[\u4e00-\u9fff])', ''),
    Rule("orphan_z_cjk_punct",
         r'(?<=[\u4e00-\u9fff])z+(?=[\s,，。；：！？、)])', ''),
    Rule("orphan_z_punct_cjk",
         r'(?<=[\s,，。；：！？、)])z+(?=[\u4e00-\u9fff])', ''),
    Rule("orphan_z_cjk_eol",
         r'(?<=[\u4e00-\u9fff])z+(?=$)', '', multiline=True),
    Rule("orphan_z_sol_cjk",
         r'(?<=^)z+(?=[\u4e00-\u9fff])', '', multiline=True),
    Rule("orphan_z_z_between",
         r'(?<=\s)z+(?=\s)', ' '),
    Rule("orphan_z_sol_line",
         r'^z+\s*', '', multiline=True),
    Rule("orphan_z_word",
         r'\bz{1,2}\b', ''),
]


def _remove_orphan_z_chars(text: str) -> str:
    return apply_rules(text, _ORPHAN_Z_RULES)


# 2. 重复标点归一化
_REPEATED_PUNCT_RULES: list[Rule] = [
    Rule("punct_dot_3plus", r'。{3,}', '。'),
    Rule("punct_comma_3plus", r'，{3,}', '，'),
    Rule("punct_enum_3plus", r'、{3,}', '、'),
    Rule("punct_semi_3plus", r'；{3,}', '；'),
    Rule("punct_colon_3plus", r'：{3,}', '：'),
    Rule("punct_dot_4plus", r'\.{4,}', '...'),
    Rule("punct_dot_3_eol", r'\.{3}(?!\.)', '。'),
    Rule("punct_zz_strip", r'zz+', ''),
]


def _fix_repeated_punctuation(text: str) -> str:
    return apply_rules(text, _REPEATED_PUNCT_RULES)


# 3. 重复中文字修复（LLM 偶发重复输出）
#
# 【重要】这里只保留"重复 3 次以上"和"3-4 字整词重复"两类。
# 曾经的 repeat_cjk_2_1 / repeat_cjk_1to4_1_cjk / repeat_cjk_2_1plus 会无条件折叠
# "ABAB"与"AA"，把中文正常词改坏 —— 实测（对 端头及超前支护…docx 回归）：
#     "一一对应"      -> "一对应"
#     "本行行长"      -> "本行长"
#     "分公司司机"    -> "分公司机"
#     "研究研究生"    -> "研究生"
#     "刚刚"          -> "刚"
# 标书里一旦投标人/采购人名称被折叠，正文名称与营业执照不一致 = 直接废标，
# 代价远大于偶尔残留一个"采用采用"。所以宁可少清洗。
_REPEATED_WORD_RULES: list[Rule] = [
    Rule("repeat_cjk_1to4_3plus", r'([\u4e00-\u9fff]{1,4})\1{2,}', r'\1'),
    Rule("repeat_cjk_3to4_1", r'([\u4e00-\u9fff]{3,4})\1', r'\1'),
    Rule("repeat_cjk_1_3plus", r'([\u4e00-\u9fff])\1{3,}', r'\1'),
]

# 受保护串：这些内容绝不参与任何折叠（叠词是正常中文，企业/项目名是法定名称）
_PROTECTED_CJK = (
    "一一", "刚刚", "常常", "渐渐", "纷纷", "往往", "仅仅", "偏偏", "明明",
    "天天", "年年", "人人", "处处", "时时", "事事", "种种", "件件", "步步",
    "悄悄", "偷偷", "默默", "徐徐", "代代", "家家", "户户", "轻轻", "缓缓",
)


def _fix_repeated_words(text: str, protect: tuple[str, ...] = ()) -> str:
    """折叠 LLM 重复输出，但先把受保护串换成哨兵，避免误伤。

    protect 传入项目名称 / 投标人名称 / 采购人名称（调用方从 Analysis 取），
    名称里含叠字（如"山西一一科技"）时不会被改坏。
    """
    sentinels: list[tuple[str, str]] = []
    protected = [p for p in (*_PROTECTED_CJK, *protect) if p and len(p) >= 2]
    # 长的先替换，避免短串先命中导致长串被拆
    for i, token in enumerate(sorted(set(protected), key=len, reverse=True)):
        if token in text:
            key = f"\ue000{i}\ue001"
            text = text.replace(token, key)
            sentinels.append((key, token))

    text = apply_rules(text, _REPEATED_WORD_RULES)

    for key, token in sentinels:
        text = text.replace(key, token)
    return text


# 4. 标题编号修复
_HEADING_NUMBER_RULES: list[Rule] = [
    Rule("heading_d_d_d", r'^(\d)#{3,4}\s+\1\s*', '### ', multiline=True),
    Rule("heading_dd_dot", r'^[dD]\s*[dD]\.\s*', '### ', multiline=True),
    Rule("heading_d_h_d", r'^(\d)#{1,2}\s+\1\s*', '### ', multiline=True),
    Rule("heading_h_d_h", r'^(#{3,4})\s+(\d)\s+\1?\s*', r'\1 ', multiline=True),
    Rule("heading_d_only", r'^#{1,2}\s+\d+\s*$', '', multiline=True),
]


def _fix_heading_numbers(text: str) -> str:
    return apply_rules(text, _HEADING_NUMBER_RULES)


# 5. Markdown 标题归一化（动态规则：依据 chapter_title 拼接）
def _build_md_heading_rules(chapter_title: str = "") -> list[Rule]:
    rules: list[Rule] = []
    if chapter_title:
        esc = re.escape(chapter_title)
        rules.extend([
            Rule("md_h_dedup_dup_title",
                 rf'^#{1,4}\s+\d+\.?\d*\s+{esc}\s*\n', '',
                 multiline=True),
            Rule("md_h1h2_remove_title",
                 rf'^#{1,2}\s+{esc}\s*\n', '',
                 multiline=True),
            Rule("md_h4_remove_title",
                 rf'^####\s+{esc}\s*\n', '',
                 multiline=True),
        ])
    rules.extend([
        Rule("md_h_lift_low_heading",
             r'^#{1,2}\s+(?!\w)', '### ', multiline=True),
        Rule("md_h_merge_consecutive",
             r'^(#{1,6})\s+(#{1,6})\s+', r'\1 ', multiline=True),
    ])
    return rules


def _normalize_markdown_headings(text: str, chapter_title: str = "") -> str:
    return apply_rules(text, _build_md_heading_rules(chapter_title))


# --- 不完整句子修复（外部 JSON 规则，缓存为 Rule 列表） ---

_RULE_LIST_CACHE: list[Rule] | None = None


def _get_cached_external_rules() -> list[Rule]:
    """从外部 JSON 规则文件加载并转换为 Rule 对象（带缓存）。"""
    global _RULE_LIST_CACHE
    if _RULE_LIST_CACHE is not None:
        return _RULE_LIST_CACHE

    data = _load_rules()
    rules: list[Rule] = []

    for i, r in enumerate(data.get("text_replacements", [])):
        pattern = r.get("pattern", "")
        if not pattern:
            continue
        rules.append(Rule(
            name=f"text_replacement_{i}",
            pattern=pattern,
            replacement=r.get("replacement", ""),
            multiline=r.get("multiline", False),
            is_regex=False,
        ))

    for i, r in enumerate(data.get("regex_replacements", [])):
        pattern = r.get("pattern", "")
        if not pattern:
            continue
        rules.append(Rule(
            name=f"regex_replacement_{i}",
            pattern=pattern,
            replacement=r.get("replacement", ""),
            multiline=r.get("multiline", False),
            is_regex=True,
        ))

    _RULE_LIST_CACHE = rules
    return rules


def _fix_incomplete_sentences(text: str) -> str:
    return apply_rules(text, _get_cached_external_rules())


def reload_rules():
    """强制重新加载规则配置文件（用于热更新）。同时清空 Rule 缓存。"""
    global _LOADED_RULES, _RULE_LIST_CACHE
    _LOADED_RULES = {}
    _RULE_LIST_CACHE = None
    return _load_rules()


# --- Gemini 复评提出的三项确定性清洗（2026-10 第 13 轮） ---

# ① 冗余四级编号标题：正文里冒出 `3.2.1.1 液压与密封系统技术指标` 这种与上级同名的
#    四级数字标题行，纯属排版噪音（全书 6 处，实测 3.2.1/3.5.1/4.2.1/7.1.1/7.4.1/8.1.1）。
#    只删"独立的编号标题行"，绝不动表格行（以 | 开头）与正文里的编号引用。
_L4_HEADING_RE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?\d+\.\d+\.\d+\.\d+[、.．]?[ \t]*\S.*$", re.M)


def _drop_redundant_level4_headings(text: str) -> str:
    if not text:
        return text
    out_lines: list[str] = []
    for ln in text.split("\n"):
        s = ln.lstrip()
        if s.startswith("|") or s.startswith(">"):
            out_lines.append(ln)          # 表格/引用行不动
            continue
        if _L4_HEADING_RE.match(ln):
            continue                       # 丢掉这一整行编号标题
        out_lines.append(ln)
    return "\n".join(out_lines)


# ② 目录索引式套话：一级/二级标题下的"过渡导语"里写
#    "由1.1.1节阐述 / 由1.1.2节展开 / 本节不对…展开 / 相关内容分别在后续章节中承接"。
#    这类句子把目录念了一遍却没给信息，是最强的 AI 感来源（用户点名要求清除）。按句删。
_INDEX_BOILERPLATE_RES = (
    re.compile(r"由\s*\d+(?:\.\d+){1,4}\s*节[^。；]{0,24}?(?:阐述|展开|完成|介绍|说明|论述|给出|呈现)"),
    re.compile(r"本节(?:不|仅|只)[^。；]{0,30}?展开"),
    re.compile(r"(?:相关|其余|上述)内容(?:分别|将)?(?:在)?(?:后续|以下|后文)章节(?:中)?(?:承接|展开|说明|论述|介绍)"),
    re.compile(r"本章(?:负责|旨在)?(?:界定|明确|概述)[^。；]{0,26}?(?:范围|角度|框架)[^。；]{0,20}?$"),
)
_SENT_SPLIT_RE = re.compile(r"[^。；！？\n]*[。；！？]")


def _strip_index_boilerplate(text: str) -> str:
    """删掉"由X.X.X节展开"这类目录索引式导语句子（按句删，不动其他句子）。"""
    if not text or not any(r.search(text) for r in _INDEX_BOILERPLATE_RES):
        return text
    kept_paras: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            kept_paras.append(para)
            continue
        sents = _SENT_SPLIT_RE.findall(para)
        tail = para[len("".join(sents)):]
        kept = [s for s in sents
                if not any(r.search(s) for r in _INDEX_BOILERPLATE_RES)]
        if not kept and sents:
            continue                       # 整段都是套话 → 整段删
        kept_paras.append("".join(kept) + tail)
    return "\n".join(kept_paras)


# ③ 尺寸片段重复笔误：`6*0.6*6*0.6*0.3m` 里多打了一组 `6*0.6*`
#    → 折叠为 `6*0.6*0.3m`。要求"同一组尺寸片段连续重复两遍以上"才折叠，
#    所以 `3200*4200*14.5m` 这类正常连乘不会被动到。
_DUP_DIM_RE = re.compile(r"((?:\d+(?:\.\d+)?\s*[*×x]\s*){2,})(?:\1)+")


def _dedup_dimension_fragments(text: str) -> str:
    if not text or "*" not in text and "×" not in text:
        return text
    return _DUP_DIM_RE.sub(r"\1", text)


# --- 主入口 ---

def clean_generated_content(
    content: str,
    chapter_title: str = "",
    protect_names: tuple[str, ...] = (),
    skip_meta_strip: bool = False,
) -> str:
    """正文清洗主入口。

    改动记录：原先的重复词规则会把中文正常词改坏（见 _REPEATED_WORD_RULES 注释），
    并新增了两步：
    - `_fix_repeated_words(content, protect_names)`：企业/项目名称先做哨兵保护；
    - `strip_meta_language`：删掉"本章旨在…/供评标委员会逐项核查打分"这类元语言
      （实测原文档 113 处），它们是把生成提示词写进了标书正文。

    skip_meta_strip=True 用于**分支章（本章概述）**：概述的职责就是交代"本章写什么、
    下级由谁展开"，天然会出现"本章主要…""本章系统…"这类措辞，而它们正是元语言
    清单里的短语 → 整句被删。实测一个 266 字的概述被删到 92 字，低于 100 字的
    "有效正文"门槛，等于**整章内容丢失**（导出时那一章近乎空白）。

    另外加了**清洗幅度安全网**（见下方 guard）：任何规则一次性删掉原文 40% 以上时，
    判定为误伤并**回退到清洗前的原文**。这是"宁可漏改不可错改、绝不为软问题丢内容"
    红线的兜底 —— 清洗是为了好看，丢正文是废标级事故，两者不可比。
    """
    if not content or not content.strip():
        return content

    original = content
    before_len = len(content)

    content = _remove_bom_and_control_chars(content)
    content = _remove_orphan_z_chars(content)
    content = _fix_repeated_words(content, protect_names)
    content = _fix_heading_numbers(content)
    content = _fix_repeated_punctuation(content)
    content = _normalize_markdown_headings(content, chapter_title)

    # Gemini 复评三项：冗余四级编号标题 / 目录索引式导语 / 尺寸片段重复
    content = _drop_redundant_level4_headings(content)
    content = _strip_index_boilerplate(content)
    content = _dedup_dimension_fragments(content)
    content = _remove_code_fences(content)
    content = _fix_br_tags(content)
    content = _normalize_whitespace(content)
    content = _remove_garbled_lines(content)

    # 元语言清理放在最后：前面的规则会把换行/表格整理好，这里按段删除才准
    if not skip_meta_strip:
        try:
            from services.generate.skills.norm_rules import strip_meta_language
            content = strip_meta_language(content)
        except Exception as exc:  # 规则出错不能影响正文产出
            logger.warning(f"[content_cleaner] 元语言清理失败，跳过: {exc}")

    content = _fix_incomplete_sentences(content)

    # ── 清洗幅度安全网 ──
    # 清洗只应"整理"，不该"删内容"。超过 40% 的删减一律判定为规则误伤。
    # 阈值取 100 字：与流水线判定"有效正文"的门槛一致（<100 字会被当成
    # 未加载/需要重新生成的章节），低于该值的碎片本来就不构成一章内容。
    #
    # 回退策略（两步，优先保住排版）：
    #   ① 先只回退"删内容"这一步（元语言剥离），格式整理（Markdown 标题归一、
    #      表格/空白整理）仍然保留 —— 这样既没丢字，正文也不至于留着 "####"；
    #   ② 若①仍然删减超 40%（说明是别的规则在删），直接回退到清洗前原文。
    after_len = len(content)
    if before_len >= 100 and after_len < before_len * 0.60:
        logger.error(
            "[content_cleaner] 清洗删减 %s -> %s 字（%.0f%%，标题=%s），判定为误伤",
            before_len, after_len, (1 - after_len / before_len) * 100, chapter_title,
        )
        if not skip_meta_strip:
            cleaned = clean_generated_content(
                original, chapter_title, protect_names, skip_meta_strip=True
            )
            if len(cleaned) >= before_len * 0.60:
                logger.error("[content_cleaner] 已改为「仅整理格式、不删内容」重跑")
                return cleaned
        logger.error("[content_cleaner] 已回退为清洗前原文")
        return original.strip()

    # 清洗幅度过大说明规则可能误伤，留痕便于追查（历史上正是这类静默改动导致正文被改坏）
    if before_len > 200 and abs(after_len - before_len) / before_len > 0.30:
        logger.warning(
            "[content_cleaner] 清洗幅度异常: %s -> %s (标题=%s)，请检查规则是否误伤",
            before_len, after_len, chapter_title,
        )

    return content.strip()


# --- 截断检测 ---

_COMPLETE_ENDINGS = re.compile(
    r'[。！？；\.\!\?\;）\)\u3011\u300b""\'\u201d]$'
)
_HEADING_ONLY = re.compile(r'^#{1,6}\s+[^\n]+$')
_INCOMPLETE_PATTERNS = [
    re.compile(r'[，、,:：]\s*$'),             # 以逗号/冒号结尾
    re.compile(r'^#{1,6}\s+[^\n]+\s*$', re.MULTILINE),  # 仅有标题无内容
    re.compile(r'\|\s*[^|]+\s*\|?\s*$'),      # 以未完成的表格行结尾
]


def is_content_truncated(content: str) -> bool:
    """检测内容是否被截断。

    通过以下方式判断：
    1. 内容以不完整的句子结尾（无句号/感叹号/问号）
    2. 内容以 Markdown 标题结尾（无正文内容）
    3. 内容以逗号/冒号结尾
    4. 内容以未完成的表格行结尾
    """
    if not content or not content.strip():
        return False

    stripped = content.rstrip()
    if not stripped:
        return False

    # 获取最后一行
    last_line = stripped.split('\n')[-1].strip()

    # 以标题结尾（无内容）
    if _HEADING_ONLY.match(last_line):
        return True

    # 以不完整标点结尾
    for pat in _INCOMPLETE_PATTERNS:
        if pat.search(stripped[-200:]):
            # 额外检查：如果最后一行是标题行，确认截断
            if _HEADING_ONLY.match(last_line):
                return True
            # 如果以逗号/冒号结尾，很可能截断
            if re.search(r'[，、,:：]\s*$', stripped):
                return True

    # 检查最后一个完整句子是否以完整标点结尾
    if not _COMPLETE_ENDINGS.search(stripped):
        return True

    return False


def get_last_complete_section(content: str) -> tuple[str, str]:
    """获取内容中最后一个完整的章节/段落。

    返回 (完整部分, 不完整尾部)。
    用于截断后续写时，将不完整尾部作为上下文传给 LLM。
    """
    if not content:
        return "", ""

    lines = content.rstrip().split('\n')
    # 从后往前找最后一个完整段落边界（## 或 ### 标题前）
    last_boundary = len(lines)
    for i in range(len(lines) - 1, max(0, len(lines) - 50), -1):
        line = lines[i].strip()
        if re.match(r'^#{2,4}\s+', line):
            # 检查这个标题下是否有实质内容（非空行）
            has_content = False
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j].strip() and not re.match(r'^#{1,6}\s+', lines[j].strip()):
                    has_content = True
                    break
            if not has_content:
                last_boundary = i
                continue
            break

    complete = '\n'.join(lines[:last_boundary]).rstrip()
    incomplete_tail = '\n'.join(lines[last_boundary:]).strip()
    return complete, incomplete_tail
