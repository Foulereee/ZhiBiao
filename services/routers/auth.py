from __future__ import annotations

import hashlib
import secrets
import time

import bcrypt
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
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Fallback for legacy SHA256 hashes
        return hashed == hashlib.sha256(password.encode("utf-8")).hexdigest()


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

    if not _verify_password(data.password, user.password_hash):
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
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from services.middleware.rbac_middleware import get_current_user
    user = await get_current_user(request, db)

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
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    from services.middleware.rbac_middleware import get_current_user
    await get_current_user(request, db)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token and token in _sessions:
            del _sessions[token]
    return {"success": True}


@router.put("/change-password")
async def change_password(
    request: Request,
    new_password: str,
    db: AsyncSession = Depends(get_db),
):
    from services.middleware.rbac_middleware import get_current_user
    user = await get_current_user(request, db)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth_header[7:].strip()
    session = verify_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")

    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度不能少于6位")

    user.password_hash = _hash_password(new_password)
    await db.flush()

    if token in _sessions:
        del _sessions[token]

    return {"success": True, "message": "密码已修改，请重新登录"}
