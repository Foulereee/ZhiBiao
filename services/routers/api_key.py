"""API Key 管理路由：签发、查询、撤销、充值。

供运营后台/管理脚本使用，使用管理员 Bearer Token 鉴权。
桌面端 VIP 用户不直接调用此路由，而是通过购买流程获得 API Key。
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from services.database import get_db
from services.models import ApiKey, ApiKeyUsage
from services.middleware.api_key import _hash_key
from services.middleware.rbac_middleware import require_permission

router = APIRouter()
logger = logging.getLogger(__name__)

# API Key 明文前缀，便于识别
_KEY_PREFIX = "bmp_"
# 默认有效期：1 年
_DEFAULT_TTL_DAYS = 365


class ApiKeyCreateRequest(BaseModel):
    user_email: str = Field(..., description="用户邮箱")
    user_name: str | None = Field(None, description="用户名")
    tier: str = Field("pro", description="free / pro / team")
    type: str = Field("subscription", description="subscription / credits")
    credits: int = Field(0, description="初始 credits 数量（仅 type=credits 时）")
    ttl_days: int = Field(_DEFAULT_TTL_DAYS, description="有效期天数")
    note: str | None = Field(None, description="备注")


class ApiKeyRechargeRequest(BaseModel):
    credits: int = Field(..., gt=0, description="充值 credits 数量")


class ApiKeyUpdateRequest(BaseModel):
    enabled: bool | None = None
    note: str | None = None
    tier: str | None = None
    expires_at: datetime | None = None


def _generate_raw_key() -> str:
    """生成 32 字节随机 API Key 明文，前缀 bmp_"""
    return _KEY_PREFIX + secrets.token_urlsafe(32)


def _build_prefix(raw: str) -> str:
    """生成展示用前缀：bmp_xxxx...yyyy（前 8 + 后 4 字符）"""
    if len(raw) <= 12:
        return raw
    return raw[:8] + "..." + raw[-4:]


def _serialize(api_key: ApiKey, include_raw: bool = False) -> dict:
    """序列化 ApiKey 为 dict，可选返回明文（仅签发时）"""
    data = {
        "id": api_key.id,
        "key_prefix": api_key.key_prefix,
        "user_email": api_key.user_email,
        "user_name": api_key.user_name,
        "tier": api_key.tier,
        "type": api_key.type,
        "credits_remaining": api_key.credits_remaining,
        "credits_total": api_key.credits_total,
        "enabled": api_key.enabled,
        "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
        "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        "note": api_key.note,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
    }
    if include_raw:
        data["api_key"] = api_key._raw_key  # 仅签发时设置
    return data


@router.post("/issue")
async def issue_api_key(
    req: ApiKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_permission("api_key.issue")),
):
    """签发新的 API Key。仅管理员可用。

    返回的 `api_key` 字段是明文，仅此一次返回，请妥善保存。
    """
    if req.type not in ("subscription", "credits"):
        raise HTTPException(status_code=400, detail="type 必须是 subscription 或 credits")
    if req.tier not in ("free", "pro", "team"):
        raise HTTPException(status_code=400, detail="tier 必须是 free / pro / team")
    if req.type == "credits" and req.credits <= 0:
        raise HTTPException(status_code=400, detail="credits 类型必须指定 credits 数量")

    raw = _generate_raw_key()
    key_hash = _hash_key(raw)
    prefix = _build_prefix(raw)

    expires_at = datetime.now(timezone.utc) + timedelta(days=req.ttl_days)
    api_key = ApiKey(
        key_hash=key_hash,
        key_prefix=prefix,
        user_email=req.user_email,
        user_name=req.user_name,
        tier=req.tier,
        type=req.type,
        credits_remaining=req.credits if req.type == "credits" else 0,
        credits_total=req.credits if req.type == "credits" else 0,
        enabled=True,
        expires_at=expires_at,
        note=req.note,
    )
    db.add(api_key)
    await db.flush()

    logger.info(f"签发 API Key: {prefix} 给 {req.user_email} (tier={req.tier}, type={req.type})")

    api_key._raw_key = raw  # 临时挂载明文用于返回
    return {
        "success": True,
        "api_key": _serialize(api_key, include_raw=True),
        "message": "请妥善保存 api_key 明文，此字段仅返回一次",
    }


@router.get("/list")
async def list_api_keys(
    email: str | None = Query(None, description="按邮箱筛选"),
    type: str | None = Query(None, description="按类型筛选"),
    enabled: bool | None = Query(None, description="按状态筛选"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_permission("api_key.list")),
):
    """查询 API Key 列表。仅管理员可用。"""
    stmt = select(ApiKey)
    if email:
        stmt = stmt.where(ApiKey.user_email == email)
    if type:
        stmt = stmt.where(ApiKey.type == type)
    if enabled is not None:
        stmt = stmt.where(ApiKey.enabled == enabled)
    stmt = stmt.order_by(ApiKey.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    items = result.scalars().all()
    return {
        "success": True,
        "total": len(items),
        "items": [_serialize(k) for k in items],
    }


@router.get("/{api_key_id}")
async def get_api_key(
    api_key_id: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_permission("api_key.list")),
):
    """查询单个 API Key 详情"""
    result = await db.execute(select(ApiKey).where(ApiKey.id == api_key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    return {"success": True, "api_key": _serialize(api_key)}


@router.patch("/{api_key_id}")
async def update_api_key(
    api_key_id: str,
    req: ApiKeyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_permission("api_key.manage")),
):
    """更新 API Key 状态（启用/禁用/调整有效期）"""
    result = await db.execute(select(ApiKey).where(ApiKey.id == api_key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    updates = {}
    if req.enabled is not None:
        updates["enabled"] = req.enabled
    if req.note is not None:
        updates["note"] = req.note
    if req.tier is not None:
        if req.tier not in ("free", "pro", "team"):
            raise HTTPException(status_code=400, detail="tier 非法")
        updates["tier"] = req.tier
    if req.expires_at is not None:
        updates["expires_at"] = req.expires_at
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        await db.execute(update(ApiKey).where(ApiKey.id == api_key_id).values(**updates))
        await db.flush()

    return {"success": True, "message": "更新成功"}


@router.delete("/{api_key_id}")
async def revoke_api_key(
    api_key_id: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_permission("api_key.manage")),
):
    """撤销 API Key（软删除：仅设置 enabled=False）"""
    result = await db.execute(select(ApiKey).where(ApiKey.id == api_key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_id)
        .values(enabled=False, updated_at=datetime.now(timezone.utc))
    )
    await db.flush()
    logger.info(f"撤销 API Key: {api_key.key_prefix}")
    return {"success": True, "message": "已撤销"}


@router.post("/{api_key_id}/recharge")
async def recharge_credits(
    api_key_id: str,
    req: ApiKeyRechargeRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_permission("api_key.manage")),
):
    """为 credits 类型的 API Key 充值"""
    result = await db.execute(select(ApiKey).where(ApiKey.id == api_key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    if api_key.type != "credits":
        raise HTTPException(status_code=400, detail="仅 credits 类型可充值")

    new_remaining = api_key.credits_remaining + req.credits
    new_total = api_key.credits_total + req.credits
    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_id)
        .values(
            credits_remaining=new_remaining,
            credits_total=new_total,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()
    logger.info(f"充值 API Key {api_key.key_prefix}: +{req.credits}，余额 {new_remaining}")
    return {
        "success": True,
        "credits_remaining": new_remaining,
        "credits_total": new_total,
    }


@router.get("/{api_key_id}/usage")
async def get_usage_stats(
    api_key_id: str,
    days: int = Query(7, le=90, description="最近 N 天的统计"),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_permission("api_key.list")),
):
    """查询 API Key 使用统计"""
    result = await db.execute(select(ApiKey).where(ApiKey.id == api_key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    # 总调用数 + 总 credits 消耗
    summary_result = await db.execute(
        select(
            func.count(ApiKeyUsage.id),
            func.coalesce(func.sum(ApiKeyUsage.credits_cost), 0),
        ).where(
            ApiKeyUsage.api_key_id == api_key_id,
            ApiKeyUsage.created_at >= since,
        )
    )
    total_calls, total_credits = summary_result.one()

    # 按端点聚合
    by_endpoint_result = await db.execute(
        select(
            ApiKeyUsage.endpoint,
            func.count(ApiKeyUsage.id),
            func.coalesce(func.sum(ApiKeyUsage.credits_cost), 0),
        ).where(
            ApiKeyUsage.api_key_id == api_key_id,
            ApiKeyUsage.created_at >= since,
        ).group_by(ApiKeyUsage.endpoint)
    )
    by_endpoint = [
        {"endpoint": ep, "calls": cnt, "credits": int(cred)}
        for ep, cnt, cred in by_endpoint_result.all()
    ]

    return {
        "success": True,
        "days": days,
        "total_calls": total_calls,
        "total_credits": int(total_credits),
        "by_endpoint": by_endpoint,
    }


# === 桌面端用户自服务接口（凭自身 API Key 查询余额）===

# 自服务依赖：延迟导入避免循环
async def _get_self_api_key(
    request: Request, db: AsyncSession = Depends(get_db)
) -> ApiKey:
    from services.middleware.api_key import _verify_api_key
    return await _verify_api_key(request, db)


@router.get("/me/info")
async def get_my_info(api_key: ApiKey = Depends(_get_self_api_key)):
    """桌面端自服务：凭自身 API Key 查询余额和状态。

    注意：此路由放在 /api/api-keys/me/info，避免与 /api/auth 冲突。
    """
    return {
        "success": True,
        "info": {
            "key_prefix": api_key.key_prefix,
            "tier": api_key.tier,
            "type": api_key.type,
            "credits_remaining": api_key.credits_remaining,
            "credits_total": api_key.credits_total,
            "enabled": api_key.enabled,
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
            "user_email": api_key.user_email,
            "user_name": api_key.user_name,
        },
    }

