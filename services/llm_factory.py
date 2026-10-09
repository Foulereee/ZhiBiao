"""LLM 网关工厂。

优先级(用户要求:平台设置里的 LLM 配置必须真正生效):

    1. 数据库 llm_provider_configs 中 is_default=True 且 enabled=True 的那条
    2. .env / 容器环境(BMP_LLM_*)

历史问题:这里以前只读 core/settings.py(.env),而 get_settings() 又把 Settings
缓存在模块级变量里 —— 所以「平台设置 → 大模型配置」改了之后对真实请求零影响,
界面上的 GET /api/llm/default-model 返回 "source": "db" 只是展示用的假象。
典型表现:数据库里配的是 sensenova-6.8-flash-lite,日志里实际请求的还是 .env 的
deepseek/glm-5.2。

实现要点:
  * get_llm_gateway() 保持无参同步签名,约 40 处调用点零改动
  * 数据库配置由 refresh_llm_config() 读入模块级缓存,应用启动时注册后台任务
    周期刷新(多 worker 下最迟 TTL 生效);配置接口改动后立即刷新
  * 每次取网关都比对"配置签名",签名变了就重建 —— 无需外部记得重置
  * 数据库不可用 / 没有启用配置时自动回落 .env,不会让服务不可用
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from core.llm_gateway.gateway import LLMGateway
from core.settings import get_settings

logger = logging.getLogger(__name__)

_gateway: LLMGateway | None = None
_gateway_signature: tuple | None = None
_db_config: dict[str, Any] | None = None

# 多 worker 场景下的最终一致窗口
REFRESH_INTERVAL = float(os.environ.get("BMP_LLM_CONFIG_TTL", "15") or 15)


def get_db_llm_config() -> dict[str, Any] | None:
    """当前生效的数据库配置(未启用则为 None)。"""
    return _db_config


def get_llm_config_source() -> str:
    """真实生效来源,供界面显示。"""
    return "db" if (_db_config and _db_config.get("api_key")) else "env"


async def refresh_llm_config() -> dict[str, Any] | None:
    """把数据库里的默认 LLM 配置读进缓存;失败时保留上一次的值(或 None)。"""
    global _db_config

    from sqlalchemy import select

    from services.database import async_session, is_db_ready
    from services.models import LLMProviderConfig

    if not is_db_ready():
        return _db_config

    try:
        session_factory = async_session()
        async with session_factory() as db:
            result = await db.execute(
                select(LLMProviderConfig)
                .where(
                    LLMProviderConfig.is_default == True,  # noqa: E712
                    LLMProviderConfig.enabled == True,  # noqa: E712
                )
                .order_by(LLMProviderConfig.updated_at.desc())
            )
            rows = result.scalars().all()
    except Exception as exc:  # 库不可用不能影响生成
        logger.warning("[LLM配置] 读取数据库配置失败,继续沿用当前配置: %s", exc)
        return _db_config

    cfg: dict[str, Any] | None = None
    for row in rows:
        if not row.api_key:
            continue
        cfg = {
            "id": row.id,
            "provider_id": row.provider_id,
            "api_key": row.api_key,
            "api_base": row.api_base or "",
            "default_model": row.default_model or "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }
        break

    if cfg != _db_config:
        logger.info(
            "[LLM配置] 已更新: source=%s provider=%s model=%s",
            "db" if cfg else "env(数据库无启用配置)",
            (cfg or {}).get("provider_id"),
            (cfg or {}).get("default_model"),
        )
    _db_config = cfg
    return cfg


async def llm_config_refresher() -> None:
    """后台任务:周期刷新数据库配置(由 services/main.py 在启动时创建)。"""
    while True:
        try:
            await refresh_llm_config()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("[LLM配置] 周期刷新失败: %s", exc)
        await asyncio.sleep(REFRESH_INTERVAL)


def _signature() -> tuple:
    settings = get_settings()
    db = _db_config
    if db and db.get("api_key"):
        return (
            "db",
            db.get("id"),
            db.get("updated_at"),
            db.get("api_key"),
            db.get("api_base"),
            db.get("default_model"),
        )
    return (
        "env",
        settings.llm_api_key,
        settings.llm_api_base,
        settings.llm_default_model,
    )


def get_llm_gateway() -> LLMGateway:
    global _gateway, _gateway_signature

    signature = _signature()
    if _gateway is not None and signature == _gateway_signature:
        return _gateway

    settings = get_settings()
    db = _db_config if (_db_config and _db_config.get("api_key")) else None
    api_key = (db or {}).get("api_key") or settings.llm_api_key
    api_base = (db or {}).get("api_base") or settings.llm_api_base
    model = (db or {}).get("default_model") or settings.llm_default_model

    logger.info(
        "[LLM配置] 构建网关 source=%s model=%s api_base=%s",
        "db" if db else "env",
        model,
        api_base,
    )
    _gateway = LLMGateway(
        {
            "providers": [
                {
                    "api_key": api_key,
                    "api_base": api_base,
                }
            ],
            "default_model": model,
            "fallback_models": [
                m.strip() for m in settings.llm_fallback_modes.split(",") if m.strip()
            ],
            "max_retries": settings.llm_max_retries,
        }
    )
    _gateway_signature = signature
    return _gateway


def reset_llm_gateway() -> None:
    """丢弃缓存的网关,下次 get_llm_gateway() 会用最新配置重建。"""
    global _gateway, _gateway_signature
    _gateway = None
    _gateway_signature = None