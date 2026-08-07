"""多源去重 (借鉴 article-generation-skill 的 deduplicate_hotspots)

按三级指纹策略去重:
1. 项目编号 (如果有,最高优先级)
2. 标题前 30 字符 + 业主单位
3. URL (兜底)
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import List, Dict


class NewsDeduplicator:
    """多源去重"""

    @staticmethod
    def compute_fingerprint(item: dict) -> str:
        """计算项目指纹 (用于跨源去重)"""
        project_code = (
            item.get("project_code")
            or (item.get("extra") or {}).get("project_code", "")
            or ""
        )
        if project_code:
            return f"CODE:{project_code}"

        title = (item.get("title") or "")[:30]
        owner = (
            item.get("owner_org")
            or (item.get("extra") or {}).get("owner", "")
            or ""
        )
        if title and owner:
            return f"TO:{title}|{owner[:20]}"

        return f"URL:{item.get('url', '')}"

    @classmethod
    def deduplicate(cls, items: List[dict]) -> List[dict]:
        """去重,合并多源信息"""
        seen: Dict[str, dict] = {}
        result: List[dict] = []

        for item in items:
            fp = cls.compute_fingerprint(item)
            if fp in seen:
                existing = seen[fp]
                # 合并来源
                src_now = item.get("source", "")
                existing_sources = existing.get("sources", [])
                if isinstance(existing_sources, list) and src_now:
                    if src_now not in existing_sources:
                        existing_sources.append(src_now)
                    existing["sources"] = existing_sources
                elif src_now:
                    existing["sources"] = [src_now]
                # 取最大 hot_score
                existing["hot_score"] = max(
                    float(existing.get("hot_score") or 0),
                    float(item.get("hot_score") or 0),
                )
            else:
                item["sources"] = [item.get("source", "")] if item.get("source") else []
                seen[fp] = item
                result.append(item)

        return result

    @classmethod
    def filter_by_time(cls, items: List[dict], max_age_hours: int = 168) -> List[dict]:
        """时间窗过滤 (默认 7 天)"""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        filtered: List[dict] = []
        for item in items:
            pub_date_str = item.get("pub_date", "")
            try:
                if isinstance(pub_date_str, str) and pub_date_str:
                    pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                else:
                    filtered.append(item)
                    continue
                if pub_date >= cutoff:
                    filtered.append(item)
            except Exception:
                filtered.append(item)
        return filtered
