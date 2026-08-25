"""数据源注册中心 (参考 article-generation-skill sources.yaml 设计)

采用 YAML + 数据库双层架构:
- YAML 定义所有预置源 (启动时加载)
- 数据库镜像可在 UI 运行时修改 enabled / 统计信息
- 启动时自动 sync_to_db (YAML -> DB)
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.models import NewsSourceRegistry


_YAML_PATH = Path(__file__).parent / "sources.yaml"
_yaml_cache: Optional[dict] = None


def load_sources_yaml() -> dict:
    """从 YAML 加载所有源 (启动时缓存,便于热重载)"""
    global _yaml_cache
    if _yaml_cache is None:
        if not _YAML_PATH.exists():
            return {}
        with open(_YAML_PATH, encoding="utf-8") as f:
            _yaml_cache = yaml.safe_load(f) or {}
    return _yaml_cache


def reload_sources_yaml() -> dict:
    """强制重新加载 YAML (用于运行时热更新)"""
    global _yaml_cache
    _yaml_cache = None
    return load_sources_yaml()


def get_all_sources() -> list[dict]:
    """获取全部源 (扁平化)"""
    yaml_data = load_sources_yaml()
    result: list[dict] = []
    for group_name, sources in yaml_data.items():
        if not isinstance(sources, list):
            continue
        for src in sources:
            result.append({**src, "group": group_name})
    return result


def get_sources_by_industry(industry_code: Optional[str] = None) -> list[dict]:
    """按行业筛选源"""
    all_sources = get_all_sources()
    if not industry_code or industry_code == "all":
        return all_sources
    return [s for s in all_sources if s.get("industry") == industry_code]


def get_sources_by_codes(codes: list[str]) -> list[dict]:
    """按 code 列表获取"""
    if not codes:
        return []
    code_set = set(codes)
    return [s for s in get_all_sources() if s.get("code") in code_set]


def get_source_by_code(code: str) -> Optional[dict]:
    """按 code 获取单个源"""
    for s in get_all_sources():
        if s.get("code") == code:
            return s
    return None


async def sync_sources_to_db(db: AsyncSession) -> int:
    """启动时同步 YAML -> 数据库 (幂等)

    已有源只更新 name/weight/description/type/url 等基础信息,
    enabled 状态以数据库为准 (保留管理员的手动配置)。
    """
    yaml_data = load_sources_yaml()
    synced = 0

    for _group_name, sources in yaml_data.items():
        if not isinstance(sources, list):
            continue
        for src in sources:
            code = src.get("code")
            if not code:
                continue

            existing_result = await db.execute(
                select(NewsSourceRegistry).where(NewsSourceRegistry.code == code)
            )
            row = existing_result.scalar_one_or_none()

            if not row:
                # 新源,按 YAML 默认配置插入
                row = NewsSourceRegistry(
                    code=code,
                    name=src.get("name", ""),
                    type=src.get("type", "rss"),
                    url=src.get("url", ""),
                    industry_code=src.get("industry", "12"),
                    weight=src.get("weight", 1.0),
                    enabled=src.get("enabled", True),
                    description=src.get("description", ""),
                    extra_config=src.get("config") or {},
                )
                db.add(row)
                synced += 1
            else:
                # 已有源,基础信息以 YAML 为准 (便于升级时统一更新)
                row.name = src.get("name", row.name)
                row.type = src.get("type", row.type)
                row.url = src.get("url", row.url)
                row.industry_code = src.get("industry", row.industry_code)
                row.weight = src.get("weight", row.weight)
                row.description = src.get("description", row.description)
                if src.get("config"):
                    row.extra_config = src["config"]

    await db.flush()
    return synced


async def toggle_source(db: AsyncSession, code: str, enabled: bool) -> bool:
    """运行时启停某个源"""
    result = await db.execute(
        select(NewsSourceRegistry).where(NewsSourceRegistry.code == code)
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    row.enabled = enabled
    await db.flush()
    return True


async def update_source_stats(
    db: AsyncSession,
    code: str,
    success: bool,
    new_items: int = 0,
    error: Optional[str] = None,
    latency_ms: int = 0,
) -> None:
    """更新源抓取统计"""
    from datetime import datetime
    result = await db.execute(
        select(NewsSourceRegistry).where(NewsSourceRegistry.code == code)
    )
    row = result.scalar_one_or_none()
    if not row:
        return

    row.last_crawled_at = datetime.utcnow()
    row.last_status = "success" if success else "failed"
    row.last_error = error
    await db.flush()
