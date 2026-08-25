"""商机价值评分引擎 (5 维综合评分)

参考 article-generation-skill 的 selector.py 思路,
结合本项目业务,设计 5 个维度的可解释评分。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass


class BusinessValueScorer:
    """商机价值评分引擎

    5 个维度 (权重可配置):
    - urgency (20%): 紧急度,基于截止日期
    - match (30%): 匹配度,基于公司画像
    - amount (20%): 金额合理性,基于公司偏好
    - region (15%): 地域偏好
    - freshness (15%): 时效性,基于发布时间
    """

    WEIGHTS = {
        "urgency": 0.20,
        "match": 0.30,
        "amount": 0.20,
        "region": 0.15,
        "freshness": 0.15,
    }

    @classmethod
    def score(cls, item: dict, company_profile: Optional[dict] = None) -> dict:
        """计算综合价值评分 0-100,返回各项明细

        Returns:
            {
                "total": 87.5,
                "urgency": 80.0,
                "match": 100.0,
                "amount": 75.0,
                "region": 100.0,
                "freshness": 90.0,
            }
        """
        profile = company_profile or {}
        detail = {
            "urgency": round(cls._urgency(item) * cls.WEIGHTS["urgency"] * 100, 2),
            "match": round(cls._match(item, profile) * cls.WEIGHTS["match"] * 100, 2),
            "amount": round(cls._amount(item, profile) * cls.WEIGHTS["amount"] * 100, 2),
            "region": round(cls._region(item, profile) * cls.WEIGHTS["region"] * 100, 2),
            "freshness": round(cls._freshness(item) * cls.WEIGHTS["freshness"] * 100, 2),
        }
        detail["total"] = round(sum(detail.values()), 2)
        return detail

    @staticmethod
    def _urgency(item: dict) -> float:
        """紧急度: 距截止天数越近分数越高"""
        deadline_str = item.get("bid_deadline") or ""
        if not deadline_str:
            return 0.5
        try:
            deadline = datetime.fromisoformat(str(deadline_str).replace("Z", "+00:00"))
            days_left = (deadline - datetime.now()).days
            if days_left < 0:
                return 0.0
            if days_left <= 1:
                return 1.0
            if days_left <= 3:
                return 0.9
            if days_left <= 7:
                return 0.7
            if days_left <= 15:
                return 0.5
            return 0.3
        except Exception:
            return 0.5

    @staticmethod
    def _match(item: dict, profile: dict) -> float:
        """匹配度: 基于公司画像 (行业 + 关键词)"""
        if not profile:
            return 0.5
        item_industry = item.get("industry_code", "")
        profile_industries = profile.get("industries", []) or []
        if item_industry and profile_industries and item_industry in profile_industries:
            return 1.0

        # 关键词匹配
        item_title = item.get("title", "")
        profile_keywords = profile.get("keywords", []) or []
        if profile_keywords:
            hit = sum(1 for kw in profile_keywords if kw in item_title)
            if hit > 0:
                return min(0.5 + hit * 0.1, 1.0)
        return 0.3

    @staticmethod
    def _amount(item: dict, profile: dict) -> float:
        """金额合理性"""
        amount = item.get("amount") or 0
        if not amount:
            return 0.5
        if not profile:
            return 0.5
        min_amount = profile.get("min_amount") or 0
        max_amount = profile.get("max_amount") or float("inf")
        if min_amount <= amount <= max_amount:
            return 1.0
        return 0.3

    @staticmethod
    def _region(item: dict, profile: dict) -> float:
        """地域偏好"""
        region = item.get("region", "")
        if not profile:
            return 0.5
        preferred = profile.get("regions", []) or []
        if region and preferred and region in preferred:
            return 1.0
        return 0.4

    @staticmethod
    def _freshness(item: dict) -> float:
        """时效性"""
        pub_str = item.get("pub_date", "")
        try:
            if isinstance(pub_str, str) and pub_str:
                pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            else:
                return 0.5
            hours_ago = (datetime.now() - pub).total_seconds() / 3600
            if hours_ago <= 6:
                return 1.0
            if hours_ago <= 24:
                return 0.9
            if hours_ago <= 48:
                return 0.7
            if hours_ago <= 72:
                return 0.5
            return 0.3
        except Exception:
            return 0.5
