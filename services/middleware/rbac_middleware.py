from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database import get_db
from services.models import (
    User,
    RBACPermission,
    RBACUserRole,
    RBACRolePermission,
)


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    from services.routers.auth import verify_token

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="未提供有效的Authorization头，请使用Bearer Token认证",
        )

    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Token不能为空")

    session = verify_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")

    user_id_str = session["user_id"]
    if not user_id_str or len(user_id_str) < 10:
        raise HTTPException(status_code=401, detail="无效的用户标识")

    result = await db.execute(select(User).where(User.id == user_id_str))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    return user


async def get_current_user_optional(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User | None:
    """可选的当前用户依赖：未登录时不抛 401,返回 None

    适用于「允许未登录使用」或「未登录时使用默认用户兜底」的端点。
    """
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None


async def check_user_permission(
    user_id: str,
    permission_code: str,
    db: AsyncSession,
) -> bool:
    perm_result = await db.execute(
        select(RBACPermission).where(RBACPermission.code == permission_code)
    )
    perm = perm_result.scalar_one_or_none()
    if not perm:
        return False

    ur_result = await db.execute(
        select(RBACUserRole.role_id).where(RBACUserRole.user_id == user_id)
    )
    role_ids = [row[0] for row in ur_result.all()]
    if not role_ids:
        return False

    rp_result = await db.execute(
        select(RBACRolePermission).where(
            RBACRolePermission.role_id.in_(role_ids),
            RBACRolePermission.permission_id == perm.id,
        )
    )
    return rp_result.scalar_one_or_none() is not None


def require_permission(permission_code: str):
    async def permission_dependency(
        request: Request, db: AsyncSession = Depends(get_db)
    ) -> User:
        user = await get_current_user(request, db)

        has_perm = await check_user_permission(user.id, permission_code, db)
        if not has_perm:
            raise HTTPException(
                status_code=403,
                detail=f"权限不足: 需要 {permission_code}",
            )
        return user

    return permission_dependency
