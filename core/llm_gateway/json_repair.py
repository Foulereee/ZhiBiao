import json
import re
from typing import Any

from core.exceptions import JsonRepairError


class JsonRepairEngine:
    @staticmethod
    def extract_json(text: str) -> str:
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

    async def repair_and_validate(
        self,
        raw_text: str,
        schema: type | None = None,
        validator: callable | None = None,
        repair_chat_fn: callable | None = None,
        max_attempts: int = 2,
    ) -> dict | list:
        text = self.extract_json(raw_text)
        parsed, error = self.try_parse(text)

        if parsed is None:
            parsed = self._basic_repair(text)
            if parsed is None and repair_chat_fn:
                parsed = await self._llm_repair(text, error, repair_chat_fn)
            if parsed is None:
                raise JsonRepairError(f"JSON修复失败: {error}")

        if isinstance(parsed, list):
            return parsed

        if schema:
            try:
                validated = schema.model_validate(parsed)
                parsed = validated.model_dump()
            except Exception as e:
                if repair_chat_fn and max_attempts > 0:
                    messages = [
                        {"role": "system", "content": "你是JSON修复专家。修复以下JSON使其符合Schema要求。只输出修复后的JSON，不要解释。"},
                        {"role": "user", "content": f"Schema错误: {e}\n当前JSON: {json.dumps(parsed, ensure_ascii=False)}"},
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
        repairs = [
            lambda t: re.sub(r",\s*([}\]])", r"\1", t),
            lambda t: re.sub(r"([{,]\s*)(\w+)(\s*:)", r'\1"\2"\3', t),
            lambda t: self._fix_truncated(t),
        ]
        for repair_fn in repairs:
            try:
                result = json.loads(repair_fn(text))
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, Exception):
                continue
        return None

    def _fix_truncated(self, text: str) -> str:
        open_braces = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")
        return text + "]" * max(0, open_brackets) + "}" * max(0, open_braces)

    async def _llm_repair(self, broken_json: str, error: str, chat_fn: callable) -> dict | None:
        messages = [
            {"role": "system", "content": "修复以下非法JSON。只输出修复后的合法JSON，不要解释。"},
            {"role": "user", "content": f"错误: {error}\n内容: {broken_json[:2000]}"},
        ]
        try:
            repaired_text = await chat_fn(messages=messages, temperature=0.1)
            repaired_text = self.extract_json(repaired_text)
            result = json.loads(repaired_text)
            return result if isinstance(result, dict) else None
        except Exception:
            return None
