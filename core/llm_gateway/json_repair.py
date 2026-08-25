"""JSON 修复引擎 — 参考 OpenBidKit 的多层容错机制。

改进点：
1. 增加 <think...</think 标签处理（推理模型输出）
2. 增加平衡括号提取策略（从文本中提取完整 JSON）
3. 增加非法转义修复（Markdown 反斜杠等）
4. 增加多种候选提取策略，逐一尝试
"""

import json
import re
import logging
from typing import Any, Callable

from core.exceptions import JsonRepairError

logger = logging.getLogger(__name__)


class JsonRepairEngine:
    @staticmethod
    def extract_json(text: str) -> str:
        """从文本中提取 JSON 内容，支持多种格式。"""
        if not text or not text.strip():
            return text

        # 1. 去除 <think...</think 标签（推理模型如 DeepSeek-R1 会输出）
        text = re.sub(r"<think.*?</think\s*>", "", text, flags=re.DOTALL)

        # 2. 尝试提取 ```json...``` 代码块
        if re.search(r"```(?:json)?\s*", text):
            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
            if match:
                return match.group(1).strip()

        return text.strip()

    @staticmethod
    def try_parse(text: str) -> tuple[dict | list | None, str | None]:
        try:
            return json.loads(text), None
        except json.JSONDecodeError as e:
            return None, str(e)

    @staticmethod
    def _extract_balanced_json_candidates(text: str) -> list[str]:
        """从文本中通过栈匹配找到所有完整的 {...} 或 [...] 结构。

        参考 OpenBidKit 的 extractBalancedJsonCandidates 实现。
        """
        candidates = []
        for open_char, close_char in [("{", "}"), ("[", "]")]:
            stack = []
            start = -1
            for i, ch in enumerate(text):
                if ch == open_char:
                    if not stack:
                        start = i
                    stack.append(ch)
                elif ch == close_char:
                    if stack and stack[-1] == open_char:
                        stack.pop()
                        if not stack and start >= 0:
                            candidates.append(text[start:i + 1])
        return candidates

    @staticmethod
    def _repair_invalid_escapes(text: str) -> str:
        """修复 JSON 字符串中的非法反斜杠转义。

        参考 OpenBidKit 的 repairInvalidJsonStringEscapes 实现。
        """
        # 修复 Markdown 特殊字符前的反斜杠（如 1\. -> 1.）
        text = re.sub(r"\\([.#$&*+<>?@^`|~])", r"\1", text)
        return text

    async def repair_and_validate(
        self,
        raw_text: str,
        schema: type | None = None,
        validator: Callable | None = None,
        repair_chat_fn: Callable | None = None,
        max_attempts: int = 2,
    ) -> dict | list:
        """多层 JSON 修复和校验。

        策略顺序（参考 OpenBidKit 的候选列表方式）：
        1. 提取 JSON（去 think 标签、代码块）
        2. 直接解析
        3. 多种候选提取 + 修复策略
        4. LLM 修复
        5. Schema / 自定义校验
        """
        text = self.extract_json(raw_text)

        # 尝试直接解析
        parsed, error = self.try_parse(text)
        if parsed is not None:
            return await self._validate_parsed(parsed, schema, validator, repair_chat_fn, max_attempts)

        # 多种候选提取和修复策略
        parsed = self._try_all_repair_strategies(text)
        if parsed is not None:
            return await self._validate_parsed(parsed, schema, validator, repair_chat_fn, max_attempts)

        # LLM 修复
        if repair_chat_fn:
            parsed = await self._llm_repair(text, error, repair_chat_fn)
            if parsed is not None:
                return await self._validate_parsed(parsed, schema, validator, repair_chat_fn, max_attempts)

        raise JsonRepairError(f"JSON修复失败: {error}")

    def _try_all_repair_strategies(self, text: str) -> dict | list | None:
        """尝试所有修复策略，返回第一个成功的结果。"""
        # 构建候选列表
        candidates = self._build_candidates(text)

        for candidate in candidates:
            # 先尝试直接解析
            parsed, _ = self.try_parse(candidate)
            if parsed is not None:
                return parsed

            # 再尝试基础修复
            repaired = self._basic_repair(candidate)
            if repaired is not None:
                return repaired

        return None

    def _build_candidates(self, text: str) -> list[str]:
        """构建 JSON 候选列表，按优先级排序。"""
        candidates = [text]  # 原始文本

        # 1. 修复非法转义
        escaped = self._repair_invalid_escapes(text)
        if escaped != text:
            candidates.append(escaped)

        # 2. 平衡括号提取
        balanced = self._extract_balanced_json_candidates(text)
        candidates.extend(balanced)

        # 3. 对平衡括号提取的结果也修复非法转义
        for b in balanced:
            escaped_b = self._repair_invalid_escapes(b)
            if escaped_b != b:
                candidates.append(escaped_b)

        # 4. 去除控制字符
        cleaned = re.sub(r"[\x00-\x1f\x7f]", "", text, flags=re.DOTALL)
        if cleaned != text:
            candidates.append(cleaned)

        # 5. 去除尾部逗号
        no_trailing = re.sub(r",\s*([}\]])", r"\1", text)
        if no_trailing != text:
            candidates.append(no_trailing)

        return candidates

    async def _validate_parsed(
        self,
        parsed: dict | list,
        schema: type | None = None,
        validator: Callable | None = None,
        repair_chat_fn: Callable | None = None,
        max_attempts: int = 2,
    ) -> dict | list:
        """对已解析的 JSON 进行 Schema 和自定义校验。"""
        if isinstance(parsed, list):
            return parsed

        if schema:
            try:
                validated = schema.model_validate(parsed)
                parsed = validated.model_dump()
            except Exception as e:
                if repair_chat_fn and max_attempts > 0:
                    messages = [
                        {
                            "role": "system",
                            "content": "你是JSON修复专家。修复以下JSON使其符合Schema要求。只输出修复后的JSON，不要解释。",
                        },
                        {
                            "role": "user",
                            "content": f"Schema错误: {e}\n当前JSON: {json.dumps(parsed, ensure_ascii=False)}",
                        },
                    ]
                    repaired_text = await repair_chat_fn(messages=messages, temperature=0.1)
                    return await self.repair_and_validate(
                        raw_text=repaired_text,
                        schema=schema,
                        validator=validator,
                        repair_chat_fn=repair_chat_fn,
                        max_attempts=max_attempts - 1,
                    )
                raise JsonRepairError(f"Schema校验失败: {e}")

        if validator:
            validator_error = validator(parsed)
            if validator_error:
                raise JsonRepairError(f"自定义校验失败: {validator_error}")

        return parsed

    def _basic_repair(self, text: str) -> dict | None:
        """基础 JSON 修复策略。"""
        repairs = [
            lambda t: re.sub(r",\s*([}\]])", r"\1", t),  # 去尾部逗号
            lambda t: re.sub(r"([{,]\s*)(\w+)(\s*:)", r'\1"\2"\3', t),  # 无引号key加引号
            lambda t: self._fix_truncated(t),  # 修复截断
            lambda t: self._fix_truncated(re.sub(r",\s*([}\]])", r"\1", t)),  # 组合
            lambda t: self._fix_truncated(re.sub(r"([{,]\s*)(\w+)(\s*:)", r'\1"\2"\3', t)),  # 组合
        ]
        for repair_fn in repairs:
            try:
                result = json.loads(repair_fn(text))
                if isinstance(result, (dict, list)):
                    return result
            except (json.JSONDecodeError, Exception):
                continue
        return None

    def _fix_truncated(self, text: str) -> str:
        """修复被截断的 JSON。"""
        text = text.rstrip()
        if text.endswith(','):
            text = text[:-1]
        # Fix truncated string values: "key": "incomplete value -> "key": null
        text = re.sub(r':\s*"[^"]*$', ': null', text)
        text = re.sub(r':\s*$', ': null', text)
        # Fix unclosed strings
        in_string = False
        escape_next = False
        for ch in text:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
        if in_string:
            text += '"'
        open_braces = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")
        if open_braces == 0 and open_brackets == 0:
            return text
        # Try different closing orders and return the first one that parses
        candidates = []
        for b_first in [True, False]:
            suffix = []
            ob, oB = open_braces, open_brackets
            if b_first:
                while ob > 0 or oB > 0:
                    if ob > 0:
                        suffix.append("}")
                        ob -= 1
                    if oB > 0:
                        suffix.append("]")
                        oB -= 1
            else:
                while ob > 0 or oB > 0:
                    if oB > 0:
                        suffix.append("]")
                        oB -= 1
                    if ob > 0:
                        suffix.append("}")
                        ob -= 1
            candidates.append(text + "".join(suffix))
        # Also try all-braces-first then all-brackets
        candidates.append(text + "}" * open_braces + "]" * open_brackets)
        candidates.append(text + "]" * open_brackets + "}" * open_braces)
        for candidate in candidates:
            try:
                result = json.loads(candidate)
                if isinstance(result, (dict, list)):
                    return candidate
            except (json.JSONDecodeError, Exception):
                continue
        # Fallback: just close everything
        return text + "}" * open_braces + "]" * open_brackets

    async def _llm_repair(self, broken_json: str, error: str, chat_fn: Callable) -> dict | None:
        """使用 LLM 修复损坏的 JSON。"""
        messages = [
            {
                "role": "system",
                "content": "修复以下非法JSON。只输出修复后的合法JSON，不要解释。如果JSON被截断，补全缺失部分使其完整。",
            },
            {
                "role": "user",
                "content": f"错误: {error}\n内容: {broken_json[:4000]}",
            },
        ]
        try:
            repaired_text = await chat_fn(
                messages=messages,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            repaired_text = self.extract_json(repaired_text)
            result = json.loads(repaired_text)
            return result if isinstance(result, (dict, list)) else None
        except Exception as e:
            logger.warning(f"[JsonRepair] LLM修复失败: {e}")
            return None
