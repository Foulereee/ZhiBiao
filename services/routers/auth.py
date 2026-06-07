from __future__ import annotations

import hashlib
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database import get_db
from services.models import User, RBACUserRole, RBACRole

router = APIRouter()

_sessions: dict[str, dict] = {}

SESSION_TTL = 86400 * 7


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenInfo(BaseModel):
    token: str
    user_id: str
    email: str
    name: str
    role: str
    avatar: str | None = None


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _cleanup_sessions():
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v["created_at"] > SESSION_TTL]
    for k in expired:
        del _sessions[k]


def verify_token(token: str) -> dict | None:
    _cleanup_sessions()
    session = _sessions.get(token)
    if not session:
        return None
    if time.time() - session["created_at"] > SESSION_TTL:
        del _sessions[token]
        return None
    return session


@router.post("/login")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if not user.password_hash:
        raise HTTPException(status_code=401, detail="该账户未设置密码，请联系管理员")

    if user.password_hash != _hash_password(data.password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    token = secrets.token_hex(32)
    _cleanup_sessions()
    _sessions[token] = {
        "user_id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "created_at": time.time(),
    }

    ur_result = await db.execute(
        select(RBACUserRole.role_id).where(RBACUserRole.user_id == user.id)
    )
    role_ids = [row[0] for row in ur_result.all()]

    roles = []
    if role_ids:
        role_result = await db.execute(
            select(RBACRole).where(RBACRole.id.in_(role_ids))
        )
        roles = [{"id": str(r.id), "name": r.name, "display_name": r.display_name} for r in role_result.scalars().all()]

    return {
        "token": token,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "avatar": user.avatar,
            "roles": roles,
        },
    }


@router.get("/me")
async def get_current_user_info(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    session = verify_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")

    result = await db.execute(select(User).where(User.id == session["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    ur_result = await db.execute(
        select(RBACUserRole.role_id).where(RBACUserRole.user_id == user.id)
    )
    role_ids = [row[0] for row in ur_result.all()]

    roles = []
    if role_ids:
        role_result = await db.execute(
            select(RBACRole).where(RBACRole.id.in_(role_ids))
        )
        roles = [{"id": str(r.id), "name": r.name, "display_name": r.display_name} for r in role_result.scalars().all()]

    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "avatar": user.avatar,
        "roles": roles,
    }


@router.post("/logout")
async def logout(token: str = ""):
    if token and token in _sessions:
        del _sessions[token]
    return {"success": True}


@router.put("/change-password")
async def change_password(
    token: str,
    old_password: str,
    new_password: str,
    db: AsyncSession = Depends(get_db),
):
    session = verify_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")

    result = await db.execute(select(User).where(User.id == session["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    if user.password_hash != _hash_password(old_password):
        raise HTTPException(status_code=400, detail="原密码错误")

    user.password_hash = _hash_password(new_password)
    await db.flush()

    return {"success": True}
