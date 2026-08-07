"""聚合处理 Skill (整合去重 + 评分 + 行业分类)

作为整个热点抓取管线的"中央处理器":
- 输入: 多源 NewsItem 列表
- 流程: 去重 -> 行业分类 -> 价值评分 -> 写库
- 输出: 写库后的 HotspotItem 摘要

遵循现有 skill 的 Skill/SkillContext/SkillResult 风格。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.skill_engine.base import Skill, SkillContext, SkillResult
from services.models import HotspotItem
from services.news.dedup import NewsDeduplicator
from services.news.scoring import BusinessValueScorer

logger = logging.getLogger(__name__)


# 匹配 4 字节 UTF-8 字符 (BMP 之外,主要为 emoji)
# 范围: U+10000 - U+10FFFF (UTF-16 代理对区)
_RE_4BYTE = re.compile(r'[\U00010000-\U0010FFFF]')

# 常见 emoji -> ASCII 文本映射 (友好降级,保留语义)
_EMOJI_REPLACE_MAP = {
    '\U0001F525': '[火]',     # 🔥
    '\U0001F680': '[火箭]',   # 🚀
    '\U0001F4A1': '[灵感]',   # 💡
    '\U0001F389': '[庆祝]',   # 🎉
    '\U0001F44D': '[赞]',     # 👍
    '\U0001F60A': ':)',       # 😊
    '\U0001F642': ':)',       # 🙂
    '\U0001F600': ':D',       # 😀
    '\u2728': '[✨]',          # ✨
    '\u2B50': '[★]',          # ⭐
    '\U0001F4CC': '[!]',      # 📌
    '\U0001F4DD': '[笔记]',   # 📝
    '\U0001F50D': '[搜索]',   # 🔍
    '\u2705': '[✓]',          # ✅
    '\u274C': '[✗]',          # ❌
    '\u26A0': '[!]',          # ⚠
    '\U0001F6E0': '[工具]',   # 🛠
}


def sanitize_for_mysql(text: str | None) -> str:
    """清理文本,使其可安全写入 MySQL utf8 (3字节) 列

    - 用友好降级映射替换常见 emoji
    - 其他 4 字节字符直接去除
    - 清理控制字符
    """
    if not text:
        return ""

    s = str(text)

    # 1) 已知 emoji 降级
    for emoji, replacement in _EMOJI_REPLACE_MAP.items():
        s = s.replace(emoji, replacement)

    # 2) 剩余 4 字节字符 → 去除
    s = _RE_4BYTE.sub('', s)

    # 3) 控制字符 (\x00 - \x08, \x0B, \x0C, \x0E - \x1F)
    s = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', s)

    return s


def sanitize_dict(data: Any) -> Any:
    """递归清理 dict/list/str 中的 4 字节字符,用于 JSON 字段 (extra)"""
    if isinstance(data, str):
        return sanitize_for_mysql(data)
    if isinstance(data, dict):
        return {k: sanitize_dict(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [sanitize_dict(v) for v in data]
    return data



class HotspotAggregateSkill(Skill):
    """聚合处理 Skill: 去重 -> 分类 -> 评分 -> 写库"""

    name = "hotspot_aggregate"
    description = "聚合多源热点: 去重 + 行业分类 + 价值评分 + 写库"
    category = "news"
    version = "1.0.0"
    triggers = ["聚合", "去重", "评分", "aggregate"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        items = ctx.parameters.get("items", []) or []
        company_profile = ctx.parameters.get("company_profile") or {}
        is_hot_threshold = float(ctx.parameters.get("is_hot_threshold", 60))
        persist = bool(ctx.parameters.get("persist", True))

        if not items:
            return SkillResult(
                success=True,
                data={"total": 0, "after_dedup": 0, "saved": 0, "items": []},
            )

        # 1) 行业分类 (Skill 调用)
        try:
            from services.news.skills.industry_classify_skill import IndustryClassifySkill
            classify_skill = IndustryClassifySkill()
            cls_ctx = SkillContext(
                project_id=ctx.project_id,
                db=ctx.db,
                llm=ctx.llm,
                parameters={"items": items},
            )
            cls_result = await classify_skill.safe_execute(cls_ctx)
            if cls_result.success and cls_result.data:
                items = cls_result.data.get("items", items)
        except Exception as e:
            logger.warning(f"行业分类子任务失败,继续后续: {e}")

        # 2) 去重
        items = NewsDeduplicator.deduplicate(items)

        # 3) 评分
        for it in items:
            try:
                score = BusinessValueScorer.score(it, company_profile)
                it["score_total"] = score.get("total", 0)
                it["score_urgency"] = score.get("urgency", 0)
                it["score_match"] = score.get("match", 0)
                it["score_amount"] = score.get("amount", 0)
                it["score_region"] = score.get("region", 0)
                it["score_freshness"] = score.get("freshness", 0)
                it["is_hot"] = score.get("total", 0) >= is_hot_threshold
            except Exception as e:
                logger.warning(f"评分失败: {e}")

        # 4) 写库 (可选)
        saved = 0
        if persist and ctx.db is not None:
            saved = await self._persist(ctx.db, items)

        return SkillResult(
            success=True,
            data={
                "total": len(items),
                "saved": saved,
                "items": [
                    {
                        "title": it.get("title", ""),
                        "url": it.get("url", ""),
                        "source": it.get("source", ""),
                        "industry_code": it.get("industry_code", ""),
                        "industry_name": it.get("industry_name", ""),
                        "region": it.get("region", ""),
                        "score_total": it.get("score_total", 0),
                        "is_hot": it.get("is_hot", False),
                    }
                    for it in items[:200]
                ],
            },
        )

    async def _persist(self, db: AsyncSession, items: list[dict]) -> int:
        """按 fingerprint 写入或更新"""
        saved = 0
        for it in items:
            try:
                fp = NewsDeduplicator.compute_fingerprint(it)
                it["fingerprint"] = fp
                existing = await db.execute(
                    select(HotspotItem).where(HotspotItem.fingerprint == fp)
                )
                row = existing.scalar_one_or_none()
                if not row:
                    # 清理字符串字段,避免 4 字节 UTF-8 字符写入 utf8 列失败
                    row = HotspotItem(
                        title=sanitize_for_mysql(it.get("title"))[:500],
                        url=sanitize_for_mysql(it.get("url", ""))[:1000],
                        source=sanitize_for_mysql(it.get("source", ""))[:500],
                        sources=it.get("sources", []) or [it.get("source", "")],
                        pub_date=it.get("pub_date", "") or "",
                        content=sanitize_for_mysql(it.get("content"))[:5000],
                        source_code=sanitize_for_mysql(it.get("source_code", ""))[:100],
                        industry_code=it.get("industry_code", "12"),
                        region=sanitize_for_mysql(it.get("region", ""))[:50],
                        amount=float(it.get("amount") or 0),
                        bid_deadline=it.get("bid_deadline", "") or "",
                        owner_org=sanitize_for_mysql(it.get("owner_org", ""))[:200],
                        project_code=sanitize_for_mysql(it.get("project_code", ""))[:100],
                        fingerprint=fp,
                        extra=sanitize_dict(it.get("extra", {})),
                        score_total=float(it.get("score_total") or 0),
                        score_urgency=float(it.get("score_urgency") or 0),
                        score_match=float(it.get("score_match") or 0),
                        score_amount=float(it.get("score_amount") or 0),
                        score_region=float(it.get("score_region") or 0),
                        score_freshness=float(it.get("score_freshness") or 0),
                        is_hot=bool(it.get("is_hot", False)),
                    )
                    db.add(row)
                else:
                    # 更新评分与合并来源
                    row.score_total = max(float(row.score_total or 0), float(it.get("score_total") or 0))
                    row.is_hot = row.is_hot or bool(it.get("is_hot", False))
                    sources = list(row.sources or [])
                    new_src = it.get("source", "")
                    if new_src and new_src not in sources:
                        sources.append(new_src)
                    row.sources = sources
                    if not row.industry_code or row.industry_code == "12":
                        row.industry_code = it.get("industry_code", "12")
                saved += 1
            except Exception as e:
                logger.warning(f"持久化热点失败: {e}")
        try:
            await db.flush()
        except Exception as e:
            logger.warning(f"flush 失败: {e}")
        return saved
