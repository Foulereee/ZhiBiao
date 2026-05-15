from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

COMMON_PHRASES = {
    "根据招标文件要求",
    "按照招标文件规定",
    "符合招标文件",
    "满足招标文件",
    "严格按照",
    "遵照执行",
    "认真贯彻落实",
    "我方承诺",
    "本公司承诺",
    "我公司将",
    "我们将",
    "确保",
    "保证",
    "严格遵守",
    "严格执行",
    "规范操作",
    "科学管理",
    "优质服务",
    "高效完成",
    "安全第一",
    "质量为本",
    "客户至上",
    "诚信经营",
}

TEMPLATE_SIGNATURES = {
    "XX公司",
    "XX项目",
    "XX市",
    "XX省",
    "XX区",
    "XXX",
    "【此处填写",
    "【请填写",
    "【待填写",
    "【替换",
    "[此处填写",
    "[请填写",
    "[待填写",
    "[替换",
}


class WhitelistFilterSkill(Skill):
    name = "whitelist_filter"
    description = "三层白名单过滤(正则→向量→LLM)"
    category = "check"
    version = "1.0.0"
    triggers = ["白名单", "过滤", "误报过滤"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        duplicate_results = ctx.parameters.get("duplicate_results", {})
        whitelist_phrases = ctx.parameters.get("whitelist_phrases", list(COMMON_PHRASES))
        use_vector = ctx.parameters.get("use_vector_filter", False)
        use_llm = ctx.parameters.get("use_llm_filter", False)

        if not duplicate_results:
            return SkillResult(success=True, data={"original_count": 0, "filtered_count": 0, "removed": []})

        matches = duplicate_results.get("matches", [])
        if not isinstance(matches, list):
            matches = []

        layer1_removed = self._regex_filter(matches, whitelist_phrases)
        remaining_after_l1 = [m for m in matches if m not in layer1_removed]

        layer2_removed = []
        if use_vector:
            layer2_removed = self._vector_filter(remaining_after_l1)

        remaining_after_l2 = [m for m in remaining_after_l1 if m not in layer2_removed]

        layer3_removed = []
        if use_llm and remaining_after_l2:
            layer3_removed = await self._llm_filter(remaining_after_l2, ctx)

        all_removed = layer1_removed + layer2_removed + layer3_removed
        final_matches = [m for m in matches if m not in all_removed]

        return SkillResult(
            success=True,
            data={
                "original_count": len(matches),
                "filtered_count": len(final_matches),
                "removed_count": len(all_removed),
                "layer1_regex_removed": len(layer1_removed),
                "layer2_vector_removed": len(layer2_removed),
                "layer3_llm_removed": len(layer3_removed),
                "removed": all_removed[:50],
                "final_matches": final_matches,
            },
        )

    def _regex_filter(self, matches: list[dict], whitelist: list[str]) -> list[dict]:
        removed = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            text = match.get("text", match.get("content", ""))
            for phrase in whitelist:
                if phrase in text:
                    match["filter_reason"] = f"白名单匹配: {phrase}"
                    removed.append(match)
                    break
        return removed

    def _vector_filter(self, matches: list[dict]) -> list[dict]:
        removed = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            similarity = match.get("similarity", match.get("score", 0))
            if isinstance(similarity, (int, float)) and similarity < 0.7:
                match["filter_reason"] = f"相似度过低: {similarity}"
                removed.append(match)
        return removed

    async def _llm_filter(self, matches: list[dict], ctx: SkillContext) -> list[dict]:
        if not matches:
            return []

        texts = []
        for i, m in enumerate(matches[:10]):
            text = m.get("text", m.get("content", ""))[:200]
            texts.append(f"{i+1}. {text}")

        messages = [
            {
                "role": "system",
                "content": """你是标书查重误报判断专家。判断以下匹配是否为误报（即不应该被标记为重复的内容）。

常见误报类型：
1. 行业标准用语和规范表述
2. 法律法规引用
3. 通用技术参数和指标
4. 招标文件原文引用
5. 常见承诺和保证用语

返回JSON: {"results": [{"index": 1, "is_false_positive": true/false, "reason": "理由"}]}""",
            },
            {
                "role": "user",
                "content": "\n".join(texts),
            },
        ]

        try:
            result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
            removed = []
            if result and "results" in result:
                for r in result["results"]:
                    idx = r.get("index", 0) - 1
                    if 0 <= idx < len(matches) and r.get("is_false_positive", False):
                        matches[idx]["filter_reason"] = f"LLM判定误报: {r.get('reason', '')}"
                        removed.append(matches[idx])
            return removed
        except Exception as e:
            logger.warning(f"LLM过滤失败: {e}")
            return []
