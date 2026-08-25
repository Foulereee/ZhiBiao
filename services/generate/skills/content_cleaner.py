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
_REPEATED_WORD_RULES: list[Rule] = [
    Rule("repeat_cjk_1to4_3plus", r'([\u4e00-\u9fff]{1,4})\1{2,}', r'\1'),
    Rule("repeat_cjk_1to4_1_cjk", r'([\u4e00-\u9fff]{1,4})\1(?=[\u4e00-\u9fff])', r'\1'),
    Rule("repeat_cjk_2_1plus", r'([\u4e00-\u9fff]{2})\1{1,}', r'\1'),
    Rule("repeat_cjk_3to4_1", r'([\u4e00-\u9fff]{3,4})\1', r'\1'),
    Rule("repeat_cjk_1_2plus", r'([\u4e00-\u9fff])\1{2,}', r'\1'),
    Rule("repeat_cjk_2_1", r'([\u4e00-\u9fff]{2})\1', r'\1'),
]


def _fix_repeated_words(text: str) -> str:
    return apply_rules(text, _REPEATED_WORD_RULES)


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


# --- 主入口 ---

def clean_generated_content(content: str, chapter_title: str = "") -> str:
    if not content or not content.strip():
        return content

    content = _remove_bom_and_control_chars(content)
    content = _remove_orphan_z_chars(content)
    content = _fix_repeated_words(content)
    content = _fix_heading_numbers(content)
    content = _fix_repeated_punctuation(content)
    content = _normalize_markdown_headings(content, chapter_title)
    content = _remove_code_fences(content)
    content = _fix_br_tags(content)
    content = _normalize_whitespace(content)
    content = _remove_garbled_lines(content)
    content = _fix_incomplete_sentences(content)

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
