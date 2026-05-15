from __future__ import annotations

import re
from typing import Any

SECTION_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百千]+[章节部分编篇]"),
    re.compile(r"^[一二三四五六七八九十]+[、．.]\s*"),
    re.compile(r"^[(（][一二三四五六七八九十]+[)）]\s*"),
    re.compile(r"^\d+[\.．]\s*\d*(?:[\.．]\d*)*\s"),
    re.compile(r"^第\d+[章节部分条]"),
    re.compile(r"^[A-Z][\.\、]\s*"),
    re.compile(r"^附[录件表]\s"),
    re.compile(r"^[（(]\d+[)）]\s*"),
]


class SectionDetector:
    def __init__(self, llm_gateway: Any | None = None):
        self.llm = llm_gateway

    def detect(self, text: str) -> list[dict]:
        sections = self._regex_detect(text)
        return sections

    async def detect_async(self, text: str) -> list[dict]:
        sections = self._regex_detect(text)
        if not sections and self.llm:
            sections = await self._ai_detect(text)
        return sections

    def _regex_detect(self, text: str) -> list[dict]:
        section_map: dict[str, dict] = {}
        for line in text.split("\n"):
            line = line.strip()
            if not line or len(line) > 500:
                continue
            for pattern in SECTION_PATTERNS:
                match = pattern.match(line)
                if match:
                    section_id = match.group(0).strip()
                    if section_id not in section_map:
                        section_map[section_id] = {
                            "id": section_id,
                            "title": line[:120],
                            "level": self._estimate_level(section_id),
                        }
                    break
        return list(section_map.values())

    async def _ai_detect(self, text: str) -> list[dict]:
        if not self.llm:
            return []
        messages = [
            {"role": "system", "content": '分析以下招标文件文本，提取所有章节标题。返回JSON数组: [{"id":"章节编号","title":"标题","level":1}]'},
            {"role": "user", "content": text[:8000]},
        ]
        result = await self.llm.collect_json(messages=messages)
        if isinstance(result, list):
            return result
        return result.get("sections", [])

    def _ai_detect_sync(self, text: str) -> list[dict]:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return []
            return loop.run_until_complete(self._ai_detect(text))
        except Exception:
            return []

    def _estimate_level(self, section_id: str) -> int:
        if re.match(r"^第[一二三四五六七八九十百千]+[章部分编篇]", section_id):
            return 1
        if re.match(r"^\d+[\.．]\s*$", section_id):
            return 1
        if re.match(r"^\d+[\.．]\d+", section_id):
            dot_match = re.search(r"[\.．]", section_id)
            if dot_match:
                parts = section_id[: dot_match.start()].split(".")
                return min(len(parts) + 1, 4)
        return 2
