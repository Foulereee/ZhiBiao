from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

EXTRACT_PATTERNS = [
    r'<article[^>]*>(.*?)</article>',
    r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
    r'<div[^>]*class="[^"]*article[^"]*"[^>]*>(.*?)</div>',
    r'<div[^>]*id="[^"]*content[^"]*"[^>]*>(.*?)</div>',
    r'<div[^>]*class="[^"]*detail[^"]*"[^>]*>(.*?)</div>',
    r'<div[^>]*class="[^"]*news[^"]*"[^>]*>(.*?)</div>',
    r'<div[^>]*class="[^"]*text[^"]*"[^>]*>(.*?)</div>',
    r'<body[^>]*>(.*?)</body>',
]

RE_HTML_TAG = re.compile(r'<[^>]+>')
RE_HTML_ENTITY = re.compile(r'&[a-zA-Z]+;')
RE_WHITESPACE = re.compile(r'\s+')
RE_DATE = re.compile(r'(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})[日号]?')
RE_MONEY = re.compile(r'(\d+(?:\.\d+)?)\s*(万元|亿元|元|万|亿)')
RE_LOCATION = re.compile(r'([\u4e00-\u9fff]{2,6}(?:省|市|区|县|镇|乡))')

HTML_ENTITY_MAP = {
    '&nbsp;': ' ', '&lt;': '<', '&gt;': '>', '&amp;': '&',
    '&quot;': '"', '&#39;': "'", '&mdash;': '—', '&ndash;': '–',
    '&ldquo;': '\u201c', '&rdquo;': '\u201d', '&lsquo;': '\u2018',
    '&rsquo;': '\u2019', '&hellip;': '\u2026',
}


class NewsCrawlerSkill(Skill):
    name = "news_crawler"
    description = "多源招标资讯爬虫"
    category = "news"
    version = "1.0.0"
    triggers = ["爬虫", "采集", "抓取", "监控"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        task_id = ctx.parameters.get("task_id", "")
        keywords = ctx.parameters.get("keywords", "")
        exclude_keywords = ctx.parameters.get("exclude_keywords", "")
        must_contain = ctx.parameters.get("must_contain_keywords", "")
        sites = ctx.parameters.get("sites", [])
        max_pages = ctx.parameters.get("max_pages", 5)

        results = []
        errors = []

        if not sites:
            sites = self._get_default_sites()

        for site_url in sites[:5]:
            try:
                page_results = await self._crawl_site(
                    site_url, keywords, exclude_keywords, must_contain, max_pages, ctx
                )
                results.extend(page_results)
            except Exception as e:
                errors.append({"site": site_url, "error": str(e)})
                logger.warning(f"爬取 {site_url} 失败: {e}")

        filtered = self._filter_results(results, keywords, exclude_keywords, must_contain)

        return SkillResult(
            success=True,
            data={
                "total_crawled": len(results),
                "after_filter": len(filtered),
                "results": filtered[:50],
                "errors": errors,
                "crawled_at": datetime.now().isoformat(),
            },
        )

    async def _crawl_site(
        self, url: str, keywords: str, exclude: str, must_contain: str, max_pages: int, ctx: SkillContext
    ) -> list[dict[str, Any]]:
        import httpx

        results = []
        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text

                items = self._parse_list_page(html, url)
                for item in items:
                    try:
                        detail_resp = await client.get(item["url"])
                        detail_resp.raise_for_status()
                        content = self._extract_content(detail_resp.text)
                        item["content"] = content
                        item["content_hash"] = hashlib.md5(content.encode()).hexdigest()
                    except Exception:
                        item["content"] = ""
                        item["content_hash"] = ""

                    results.append(item)

        except Exception as e:
            logger.warning(f"HTTP请求失败 {url}: {e}")

        return results

    def _parse_list_page(self, html: str, base_url: str) -> list[dict[str, Any]]:
        items = []
        link_pattern = re.compile(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.DOTALL)
        matches = link_pattern.findall(html)

        seen = set()
        for href, text in matches:
            text = RE_HTML_TAG.sub('', text).strip()
            if len(text) < 6 or len(text) > 200:
                continue
            if not RE_DATE.search(text) and not re.search(r'[\u4e00-\u9fff]{4,}', text):
                continue

            full_url = self._resolve_url(base_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            date_match = RE_DATE.search(text)
            pub_date = ""
            if date_match:
                pub_date = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"

            items.append({
                "title": text[:100],
                "url": full_url,
                "pub_date": pub_date,
                "source": base_url,
            })

        return items[:20]

    def _extract_content(self, html: str) -> str:
        for pattern in EXTRACT_PATTERNS:
            matches = re.findall(pattern, html, re.DOTALL)
            if matches:
                longest = max(matches, key=len)
                text = RE_HTML_TAG.sub('', longest)
                text = self._decode_entities(text)
                text = RE_WHITESPACE.sub(' ', text).strip()
                if len(text) > 100:
                    return text

        text = RE_HTML_TAG.sub('', html)
        text = self._decode_entities(text)
        text = RE_WHITESPACE.sub(' ', text).strip()
        return text[:5000]

    def _decode_entities(self, text: str) -> str:
        for entity, char in HTML_ENTITY_MAP.items():
            text = text.replace(entity, char)
        text = RE_HTML_ENTITY.sub('', text)
        return text

    def _resolve_url(self, base: str, href: str) -> str:
        if href.startswith('http'):
            return href
        if href.startswith('//'):
            return 'https:' + href
        if href.startswith('/'):
            from urllib.parse import urlparse
            parsed = urlparse(base)
            return f"{parsed.scheme}://{parsed.netloc}{href}"
        return f"{base.rstrip('/')}/{href.lstrip('/')}"

    def _filter_results(
        self, results: list[dict], keywords: str, exclude: str, must_contain: str
    ) -> list[dict]:
        filtered = []
        kw_list = [k.strip() for k in keywords.split(',') if k.strip()] if keywords else []
        ex_list = [k.strip() for k in exclude.split(',') if k.strip()] if exclude else []
        must_list = [k.strip() for k in must_contain.split(',') if k.strip()] if must_contain else []

        for item in results:
            text = f"{item.get('title', '')} {item.get('content', '')}".lower()

            if ex_list and any(ex.lower() in text for ex in ex_list):
                continue

            if must_list and not all(m.lower() in text for m in must_list):
                continue

            if kw_list:
                score = sum(1 for kw in kw_list if kw.lower() in text)
                if score == 0:
                    continue
                item["keyword_score"] = score

            filtered.append(item)

        filtered.sort(key=lambda x: x.get("keyword_score", 0), reverse=True)
        return filtered

    def _get_default_sites(self) -> list[str]:
        return [
            "https://www.chinabidding.cn/search/proj",
            "https://bulletin.cebpubservice.com/",
            "https://www.ccgp.gov.cn/cggg/zygg/",
            "https://www.bidcenter.com.cn/search",
            "https://www.bidlink.cn/search",
        ]


class AISemanticFilterSkill(Skill):
    name = "ai_semantic_filter"
    description = "AI语义过滤(判断资讯相关性)"
    category = "news"
    version = "1.0.0"
    triggers = ["语义过滤", "相关性", "AI过滤"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        items = ctx.parameters.get("items", [])
        company_profile = ctx.parameters.get("company_profile", "")
        threshold = ctx.parameters.get("threshold", 0.6)

        if not items:
            return SkillResult(success=True, data={"filtered": [], "total": 0, "relevant": 0})

        if not company_profile:
            return SkillResult(success=True, data={"filtered": items, "total": len(items), "relevant": len(items)})

        relevant_items = []
        batch_size = 5

        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_text = ""
            for idx, item in enumerate(batch):
                title = item.get("title", "")
                content = item.get("content", "")[:300]
                batch_text += f"\n---资讯{idx+1}---\n标题: {title}\n内容: {content}\n"

            messages = [
                {
                    "role": "system",
                    "content": f"""你是招标资讯相关性判断专家。根据企业画像判断每条资讯是否与该企业相关。

企业画像: {company_profile}

对每条资讯返回JSON:
{{
  "results": [
    {{"index": 1, "relevant": true/false, "score": 0.0-1.0, "reason": "判断理由"}}
  ]
}}

相关性阈值: {threshold}，score >= {threshold} 为相关。""",
                },
                {"role": "user", "content": batch_text},
            ]

            try:
                result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
                if result and "results" in result:
                    for r in result["results"]:
                        idx = r.get("index", 0) - 1
                        if 0 <= idx < len(batch):
                            score = r.get("score", 0)
                            batch[idx]["relevance_score"] = score
                            batch[idx]["relevance_reason"] = r.get("reason", "")
                            if score >= threshold:
                                relevant_items.append(batch[idx])
            except Exception as e:
                logger.warning(f"AI语义过滤失败: {e}")
                relevant_items.extend(batch)

        return SkillResult(
            success=True,
            data={
                "filtered": relevant_items,
                "total": len(items),
                "relevant": len(relevant_items),
                "threshold": threshold,
            },
        )


class NotificationSkill(Skill):
    name = "notification"
    description = "多通道通知推送"
    category = "news"
    version = "1.0.0"
    triggers = ["通知", "推送", "提醒"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        title = ctx.parameters.get("title", "招标资讯通知")
        content = ctx.parameters.get("content", "")
        channels = ctx.parameters.get("channels", ["desktop"])
        webhook_url = ctx.parameters.get("webhook_url", "")
        email_to = ctx.parameters.get("email_to", "")

        results = {}

        if "desktop" in channels:
            results["desktop"] = {"status": "sent", "title": title}

        if "webhook" in channels and webhook_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(webhook_url, json={
                        "title": title,
                        "content": content,
                        "type": "bid_news",
                    })
                    results["webhook"] = {"status": "sent" if resp.status_code == 200 else "failed", "code": resp.status_code}
            except Exception as e:
                results["webhook"] = {"status": "failed", "error": str(e)}

        if "email" in channels and email_to:
            results["email"] = {"status": "configured", "to": email_to}

        return SkillResult(
            success=True,
            data={
                "notification_results": results,
                "channels_used": list(results.keys()),
            },
        )
