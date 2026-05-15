from __future__ import annotations

import difflib
import logging
import re

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

HIGH_SIMILARITY_THRESHOLD = 0.7


class DuplicateCheckSkill(Skill):
    name = "duplicate_check"
    description = "标书查重检测"
    category = "check"
    version = "2.0.0"
    triggers = ["查重", "重复", "抄袭检测"]

    def _compute_text_similarity(self, text1: str, text2: str) -> float:
        return difflib.SequenceMatcher(None, text1, text2).ratio()

    def _compute_jaccard_similarity(self, text1: str, text2: str) -> float:
        words1 = set(text1.split())
        words2 = set(text2.split())
        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def _compute_structure_similarity(self, sections1: list, sections2: list) -> float:
        titles1 = set(s.strip().lower() for s in sections1 if s.strip())
        titles2 = set(s.strip().lower() for s in sections2 if s.strip())
        if not titles1 and not titles2:
            return 1.0
        if not titles1 or not titles2:
            return 0.0
        intersection = titles1 & titles2
        union = titles1 | titles2
        return len(intersection) / len(union)

    def _compute_ngram_overlap(self, text1: str, text2: str, n: int = 3) -> float:
        def _ngrams(text: str, n: int) -> set:
            chars = text.replace(" ", "")
            if len(chars) < n:
                return set()
            return {chars[i:i + n] for i in range(len(chars) - n + 1)}
        ngrams1 = _ngrams(text1, n)
        ngrams2 = _ngrams(text2, n)
        if not ngrams1 and not ngrams2:
            return 1.0
        if not ngrams1 or not ngrams2:
            return 0.0
        intersection = ngrams1 & ngrams2
        union = ngrams1 | ngrams2
        return len(intersection) / len(union)

    def _sliding_window_compare(
        self, text1: str, text2: str, window: int = 200, step: int = 100
    ) -> list[dict]:
        results = []
        len1 = len(text1)
        len2 = len(text2)
        if len1 < window or len2 < window:
            sim = self._compute_text_similarity(text1, text2)
            if sim >= HIGH_SIMILARITY_THRESHOLD:
                results.append({
                    "text1_start": 0,
                    "text1_end": len1,
                    "text2_start": 0,
                    "text2_end": len2,
                    "similarity": round(sim, 4),
                    "preview": text1[:100],
                })
            return results

        for i in range(0, len1 - window + 1, step):
            seg1 = text1[i:i + window]
            best_sim = 0.0
            best_j = 0
            for j in range(0, len2 - window + 1, step):
                seg2 = text2[j:j + window]
                sim = difflib.SequenceMatcher(None, seg1, seg2).ratio()
                if sim > best_sim:
                    best_sim = sim
                    best_j = j
            if best_sim >= HIGH_SIMILARITY_THRESHOLD:
                results.append({
                    "text1_start": i,
                    "text1_end": i + window,
                    "text2_start": best_j,
                    "text2_end": best_j + window,
                    "similarity": round(best_sim, 4),
                    "preview": seg1[:100],
                })
        return results

    def _extract_sections(self, text: str) -> list[str]:
        patterns = [
            r"第[一二三四五六七八九十百千\d]+[章节篇部]\s*[^\n]+",
            r"[一二三四五六七八九十百千]+[、.]\s*[^\n]+",
            r"\d+[、.]\s*[^\n]+",
            r"[\u4e00-\u9fff]{2,10}[:：]",
        ]
        sections = []
        for pattern in patterns:
            sections.extend(re.findall(pattern, text))
        return sections

    def _check_internal_duplicate(self, text: str) -> dict:
        paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
        duplicates = []
        seen = []
        for i, para in enumerate(paragraphs):
            for j, (prev_para, prev_idx) in enumerate(seen):
                sim = self._compute_text_similarity(para, prev_para)
                if sim >= HIGH_SIMILARITY_THRESHOLD:
                    duplicates.append({
                        "section_a": f"段落{prev_idx + 1}",
                        "section_b": f"段落{i + 1}",
                        "similarity": round(sim, 4),
                        "content_preview": para[:100],
                    })
                    break
            seen.append((para, i))

        return {
            "found": len(duplicates) > 0,
            "sections": duplicates[:20],
            "max_similarity": max((d["similarity"] for d in duplicates), default=0.0),
        }

    def _check_external_similarity(self, bid_text: str, reference_texts: list[str]) -> dict:
        if not reference_texts:
            return {
                "max_similarity": 0.0,
                "similar_sections": [],
            }

        all_similar = []
        max_sim = 0.0
        for idx, ref_text in enumerate(reference_texts[:5]):
            seq_sim = self._compute_text_similarity(bid_text, ref_text)
            jaccard_sim = self._compute_jaccard_similarity(bid_text, ref_text)
            ngram_sim = self._compute_ngram_overlap(bid_text, ref_text)

            combined = max(seq_sim, jaccard_sim, ngram_sim)
            max_sim = max(max_sim, combined)

            sliding_results = self._sliding_window_compare(bid_text, ref_text)

            bid_sections = self._extract_sections(bid_text)
            ref_sections = self._extract_sections(ref_text)
            struct_sim = self._compute_structure_similarity(bid_sections, ref_sections)

            for seg in sliding_results[:10]:
                all_similar.append({
                    "bid_section": f"位置{seg['text1_start']}-{seg['text1_end']}",
                    "ref_index": idx,
                    "similarity": seg["similarity"],
                    "content_preview": seg["preview"],
                })

            if struct_sim >= HIGH_SIMILARITY_THRESHOLD:
                all_similar.append({
                    "bid_section": "章节结构",
                    "ref_index": idx,
                    "similarity": round(struct_sim, 4),
                    "content_preview": "章节标题高度相似",
                })

        all_similar.sort(key=lambda x: x["similarity"], reverse=True)

        return {
            "max_similarity": round(max_sim, 4),
            "similar_sections": all_similar[:20],
            "algorithm_scores": {
                "sequence_matcher": round(seq_sim, 4) if reference_texts else 0.0,
                "jaccard": round(jaccard_sim, 4) if reference_texts else 0.0,
                "ngram_overlap": round(ngram_sim, 4) if reference_texts else 0.0,
            },
        }

    async def _llm_deep_analysis(
        self, ctx: SkillContext, bid_text: str, ref_content: str, algo_result: dict
    ) -> dict | None:
        try:
            messages = [
                {
                    "role": "system",
                    "content": """你是标书查重检测专家。算法已初步检测出相似度，请进行深度语义分析：

1. 内部重复：同一投标文件中是否有大段重复内容
2. 模板痕迹：是否直接复制了通用模板而未修改项目特定信息
3. 与参考文档相似度：如果提供了参考文档，检测语义层面的相似度
4. 改写检测：是否存在换词不改意的改写抄袭

返回JSON:
{
  "internal_duplicate": {
    "found": true/false,
    "sections": [
      {"section_a": "位置1", "section_b": "位置2", "similarity": 0.95, "content_preview": "重复内容预览"}
    ]
  },
  "template_traces": {
    "found": true/false,
    "items": [
      {"content": "通用模板内容", "location": "位置", "suggestion": "修改建议"}
    ]
  },
  "external_similarity": {
    "max_similarity": 0.0,
    "similar_sections": [
      {"bid_section": "投标文件位置", "ref_index": 0, "similarity": 0.85, "content_preview": "相似内容预览"}
    ]
  },
  "paraphrase_detected": {
    "found": true/false,
    "items": [
      {"original": "原文表述", "paraphrased": "改写表述", "location": "位置"}
    ]
  },
  "overall_risk": "high/medium/low",
  "duplicate_score": 0-100,
  "has_critical_issues": true/false
}""",
                },
                {
                    "role": "user",
                    "content": (
                        f"投标文件：\n{bid_text[:5000]}"
                        + (f"\n\n参考文档：\n{ref_content}" if ref_content else "")
                        + f"\n\n算法初步检测结果：\n{algo_result}"
                    ),
                },
            ]
            result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
            if isinstance(result, dict):
                result.setdefault("has_critical_issues", result.get("overall_risk") == "high")
            return result
        except Exception as e:
            logger.warning(f"LLM深度分析失败: {e}")
            return None

    async def execute(self, ctx: SkillContext) -> SkillResult:
        bid_text = ctx.parameters.get("bid_text", "")
        reference_texts = ctx.parameters.get("reference_texts", [])

        if not bid_text:
            return SkillResult(success=False, error="投标文件内容为空")

        internal_dup = self._check_internal_duplicate(bid_text)

        external_sim = self._check_external_similarity(bid_text, reference_texts)

        algo_max_sim = max(
            internal_dup.get("max_similarity", 0.0),
            external_sim.get("max_similarity", 0.0),
        )

        if algo_max_sim >= HIGH_SIMILARITY_THRESHOLD:
            overall_risk = "high"
        elif algo_max_sim >= 0.4:
            overall_risk = "medium"
        else:
            overall_risk = "low"

        duplicate_score = min(100, round(algo_max_sim * 100))

        algo_result = {
            "internal_duplicate": internal_dup,
            "external_similarity": external_sim,
            "overall_risk": overall_risk,
            "duplicate_score": duplicate_score,
            "has_critical_issues": overall_risk == "high",
            "method": "algorithm",
        }

        llm_analysis = None
        if overall_risk in ("medium", "high") or ctx.parameters.get("enable_llm_analysis", False):
            ref_content = ""
            if reference_texts:
                ref_content = "\n\n---\n\n".join(
                    f"参考文档{i+1}：\n{t[:2000]}" for i, t in enumerate(reference_texts[:5])
                )
            llm_analysis = await self._llm_deep_analysis(
                ctx, bid_text, ref_content, str(algo_result)
            )

        if llm_analysis and isinstance(llm_analysis, dict):
            llm_risk = llm_analysis.get("overall_risk", "low")
            risk_priority = {"high": 3, "medium": 2, "low": 1}
            if risk_priority.get(llm_risk, 0) > risk_priority.get(overall_risk, 0):
                overall_risk = llm_risk

            llm_score = llm_analysis.get("duplicate_score", 0)
            duplicate_score = max(duplicate_score, llm_score)

            has_critical = (
                overall_risk == "high"
                or llm_analysis.get("has_critical_issues", False)
            )

            combined = {
                "internal_duplicate": llm_analysis.get("internal_duplicate", internal_dup),
                "external_similarity": llm_analysis.get("external_similarity", external_sim),
                "template_traces": llm_analysis.get("template_traces", {"found": False, "items": []}),
                "paraphrase_detected": llm_analysis.get("paraphrase_detected", {"found": False, "items": []}),
                "algorithm_scores": external_sim.get("algorithm_scores", {}),
                "overall_risk": overall_risk,
                "duplicate_score": duplicate_score,
                "has_critical_issues": has_critical,
                "method": "algorithm+llm",
            }
        else:
            combined = algo_result

        return SkillResult(success=True, data=combined)
