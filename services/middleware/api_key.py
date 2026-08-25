"""API Key 中间件：桌面端 VIP 用户访问服务端的简化认证。

替代传统 RBAC Bearer Token，只验证 X-API-Key header 的有效性。

设计要点：
- 单一凭证：一个 ApiKey 即可访问所有已授权端点
- 双重类型：subscription (订阅制，无限次数据服务) / credits (按量付费，算力服务扣 credits)
- 与 RBAC 并存：Web 端继续用 Bearer Token，桌面端用 X-API-Key
- 安全性：只存 hash，明文仅在签发时返回一次

使用方式：
    @router.get("/today-hot", dependencies=[Depends(require_api_key)])
    async def today_hot(...): ...

    @router.post("/generate", dependencies=[Depends(require_api_key_with_credits(cost=1))])
    async def generate(...): ...
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.database import get_db
from services.models import ApiKey, ApiKeyUsage

logger = logging.getLogger(__name__)

# 允许跳过 API Key 验证的开发模式（环境变量控制）
import os
_DEV_BYPASS = os.environ.get("BIDMASTER_DEV_BYPASS_API_KEY", "").lower() in ("1", "true", "yes")


def _hash_key(raw: str) -> str:
    """sha256 哈希，前端发送的 ApiKey 明文 -> 数据库存储的 hash"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_api_key(request: Request) -> str | None:
    """从请求中提取 API Key：优先 X-API-Key header，其次 Authorization: ApiKey xxx"""
    key = request.headers.get("X-API-Key", "").strip()
    if key:
        return key
    auth = request.headers.get("Authorization", "")
    if auth.startswith("ApiKey "):
        return auth[7:].strip()
    return None


async def _verify_api_key(request: Request, db: AsyncSession) -> ApiKey:
    """验证 API Key，返回 ApiKey 实体。失败抛 401。"""
    raw = _extract_api_key(request)
    if not raw:
        raise HTTPException(status_code=401, detail="缺少 API Key，请提供 X-API-Key 头")

    key_hash = _hash_key(raw)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=401, detail="API Key 无效")
    if not api_key.enabled:
        raise HTTPException(status_code=403, detail="API Key 已被禁用")
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="API Key 已过期")

    # 记录最后使用时间（异步不阻塞）
    try:
        await db.execute(
            update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=datetime.now(timezone.utc))
        )
        await db.flush()
    except Exception as e:
        logger.warning(f"更新 API Key last_used_at 失败: {e}")

    # 记录调用日志（仅记录非 GET 请求或错误，避免日志爆炸）
    if request.method != "GET":
        try:
            usage = ApiKeyUsage(
                api_key_id=api_key.id,
                endpoint=request.url.path[:200],
                method=request.method,
                status_code=200,
                user_agent=request.headers.get("User-Agent", "")[:256],
                client_ip=request.client.host if request.client else None,
            )
            db.add(usage)
            await db.flush()
        except Exception as e:
            logger.warning(f"记录 API Key 调用日志失败: {e}")

    return api_key


async def require_api_key(request: Request, db: AsyncSession = Depends(get_db)) -> ApiKey:
    """依赖项：要求有效 API Key（任何 type 均可）"""
    if _DEV_BYPASS:
        # 开发模式：返回一个虚拟的 ApiKey 对象
        return ApiKey(
            id="dev", key_hash="dev", key_prefix="dev",
            user_email="dev@local", user_name="Developer",
            tier="team", type="subscription",
            credits_remaining=9999, credits_total=9999,
            enabled=True,
        )
    return await _verify_api_key(request, db)


async def require_api_key_subscription(
    request: Request, db: AsyncSession = Depends(get_db)
) -> ApiKey:
    """依赖项：要求 subscription 类型的 API Key（数据服务：热点、模板）"""
    if _DEV_BYPASS:
        return await require_api_key(request, db)
    api_key = await _verify_api_key(request, db)
    if api_key.type not in ("subscription", "credits"):
        raise HTTPException(status_code=403, detail="此 API Key 无权访问数据服务")
    return api_key


async def require_api_key_credits(
    request: Request, db: AsyncSession = Depends(get_db)
) -> ApiKey:
    """依赖项：要求 credits 类型的 API Key（算力服务：AI 配图、MinerU）

    仅验证 Key 有效性，不在此处扣费。扣费由具体路由调用 consume_credits() 完成，
    因为不同算力服务消耗的 credits 数量不同。
    """
    if _DEV_BYPASS:
        return await require_api_key(request, db)
    api_key = await _verify_api_key(request, db)
    if api_key.type != "credits":
        raise HTTPException(status_code=403, detail="此操作需要算力服务 API Key")
    if api_key.credits_remaining <= 0:
        raise HTTPException(status_code=402, detail="Credits 余额不足，请充值")
    return api_key


async def consume_credits(
    db: AsyncSession, api_key: ApiKey, cost: int, endpoint: str, method: str = "POST"
) -> int:
    """扣费：在算力服务完成后调用。返回扣费后的余额。失败抛 402。"""
    if cost <= 0:
        return api_key.credits_remaining

    if api_key.credits_remaining < cost:
        raise HTTPException(
            status_code=402,
            detail=f"Credits 余额不足：需要 {cost}，剩余 {api_key.credits_remaining}",
        )

    new_balance = api_key.credits_remaining - cost
    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key.id)
        .values(credits_remaining=new_balance, updated_at=datetime.now(timezone.utc))
    )

    # 写入扣费日志
    usage = ApiKeyUsage(
        api_key_id=api_key.id,
        endpoint=endpoint[:200],
        method=method,
        status_code=200,
        credits_cost=cost,
    )
    db.add(usage)
    await db.flush()

    # 同步内存中的对象
    api_key.credits_remaining = new_balance
    logger.info(f"API Key {api_key.key_prefix} 扣费 {cost}，余额 {new_balance}")
    return new_balance


async def refund_credits(
    db: AsyncSession, api_key: ApiKey, amount: int, endpoint: str
) -> int:
    """退款：算力服务失败时回退 credits。返回退款后的余额。"""
    if amount <= 0:
        return api_key.credits_remaining
    new_balance = api_key.credits_remaining + amount
    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key.id)
        .values(credits_remaining=new_balance, updated_at=datetime.now(timezone.utc))
    )
    usage = ApiKeyUsage(
        api_key_id=api_key.id,
        endpoint=endpoint[:200],
        method="REFUND",
        status_code=200,
        credits_cost=-amount,  # 负数表示退款
    )
    db.add(usage)
    await db.flush()
    api_key.credits_remaining = new_balance
    return new_balance


# === 双认证：API Key 或 Bearer Token 二选一 ===
# 用于桌面端（API Key）和 Web 端（Bearer Token）共用同一端点

class AuthPrincipal:
    """统一认证主体：封装 API Key 用户或 RBAC User"""

    def __init__(self, source: str, api_key: ApiKey | None = None, user=None):
        self.source = source  # "api_key" | "bearer" | "dev"
        self.api_key = api_key
        self.user = user

    @property
    def is_api_key(self) -> bool:
        return self.source == "api_key"

    @property
    def is_dev(self) -> bool:
        return self.source == "dev"

    @property
    def identifier(self) -> str:
        if self.is_api_key:
            return self.api_key.key_prefix
        if self.user is not None:
            return getattr(self.user, "email", "unknown")
        return "dev"


async def require_any_auth(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AuthPrincipal:
    """双认证依赖：优先 API Key，其次 Bearer Token，开发模式放行。

    用于同时服务桌面端（API Key）和 Web 端（Bearer Token）的端点。
    """
    if _DEV_BYPASS:
        return AuthPrincipal(source="dev")

    raw = _extract_api_key(request)
    if raw:
        api_key = await _verify_api_key(request, db)
        return AuthPrincipal(source="api_key", api_key=api_key)

    # 尝试 Bearer Token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        from services.middleware.rbac_middleware import get_current_user
        try:
            user = await get_current_user(request, db)
            return AuthPrincipal(source="bearer", user=user)
        except HTTPException:
            pass

    raise HTTPException(
        status_code=401,
        detail="未提供有效凭证，请使用 X-API-Key 或 Authorization: Bearer 头",
    )
