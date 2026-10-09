"""新主机初始化：建 RBAC 权限/角色 + 创建管理员账号（幂等，可重复执行）。

用途：**全新空数据库**部署时使用（迁移数据的部署方式不需要跑它，因为用户随库一起过来了）。

用法（在 api 容器内执行，或在有依赖的本地环境执行）：
    # 指定账号密码
    ADMIN_EMAIL=me@example.com ADMIN_PASSWORD='强密码' python seed_admin.py
    # 不指定密码则自动生成一个随机密码并打印一次（请立即保存）
    ADMIN_EMAIL=me@example.com python seed_admin.py

环境变量：
    ADMIN_EMAIL     管理员登录邮箱（必填，默认 admin@bidmaster.pro 并给出告警）
    ADMIN_PASSWORD  管理员密码（可选；不填则随机生成 16 位并打印）
    ADMIN_NAME      显示名（默认「系统管理员」）
"""
import asyncio
import os
import secrets
import string
import sys

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, "/app")

from core.settings import get_settings  # noqa: E402
from services.models import (  # noqa: E402
    RBACPermission,
    RBACRole,
    RBACRolePermission,
    RBACUserRole,
    User,
)
from services.routers.rbac import DEFAULT_PERMISSIONS, DEFAULT_ROLES  # noqa: E402


def _random_password(n: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(n))


async def main() -> None:
    email = (os.environ.get("ADMIN_EMAIL") or "").strip()
    if not email:
        email = "admin@bidmaster.pro"
        print("  ! 未指定 ADMIN_EMAIL，使用默认 %s —— 部署后请立刻改掉密码/邮箱" % email)
    name = os.environ.get("ADMIN_NAME") or "系统管理员"
    password = os.environ.get("ADMIN_PASSWORD") or ""
    generated = False
    if not password:
        password = _random_password()
        generated = True

    engine = create_async_engine(get_settings().get_database_url())
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        # 1) 权限
        perm_map: dict[str, str] = {}
        for category, perms in DEFAULT_PERMISSIONS.items():
            for code, pname in perms:
                existing = (await db.execute(
                    select(RBACPermission).where(RBACPermission.code == code)
                )).scalar_one_or_none()
                if existing:
                    perm_map[code] = existing.id
                else:
                    perm = RBACPermission(code=code, name=pname, category=category)
                    db.add(perm)
                    await db.flush()
                    perm_map[code] = perm.id
        all_perm_ids = list(perm_map.values())

        # 2) 角色 + 角色-权限绑定
        roles_map: dict[str, RBACRole] = {}
        for role_name, role_def in DEFAULT_ROLES.items():
            role = (await db.execute(
                select(RBACRole).where(RBACRole.name == role_name)
            )).scalar_one_or_none()
            if not role:
                role = RBACRole(
                    name=role_name,
                    display_name=role_def["display_name"],
                    is_system=role_def.get("is_system", False),
                )
                db.add(role)
                await db.flush()
            roles_map[role_name] = role

            if role_def.get("permissions") == "ALL":
                target = all_perm_ids
            elif "excluded" in role_def:
                excluded = set(role_def["excluded"])
                target = [pid for code, pid in perm_map.items() if code not in excluded]
            else:
                target = [perm_map[c] for c in role_def.get("permissions", []) if c in perm_map]

            for pid in target:
                exists = (await db.execute(
                    select(RBACRolePermission).where(
                        RBACRolePermission.role_id == role.id,
                        RBACRolePermission.permission_id == pid,
                    )
                )).scalar_one_or_none()
                if not exists:
                    db.add(RBACRolePermission(role_id=role.id, permission_id=pid))
        await db.flush()

        # 3) 管理员账号
        admin = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        created = False
        if not admin:
            admin = User(
                email=email,
                name=name,
                role="admin",
                password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            )
            db.add(admin)
            await db.flush()
            created = True

        # 4) 绑定 admin 角色
        admin_role = roles_map.get("admin")
        if admin_role:
            exists = (await db.execute(
                select(RBACUserRole).where(
                    RBACUserRole.user_id == admin.id,
                    RBACUserRole.role_id == admin_role.id,
                )
            )).scalar_one_or_none()
            if not exists:
                db.add(RBACUserRole(user_id=admin.id, role_id=admin_role.id))

        await db.commit()
        print("  权限 %d 个 / 角色 %d 个 / 管理员 %s（%s）"
              % (len(perm_map), len(roles_map), admin.email, "新建" if created else "已存在，未改动"))
        if created and generated:
            print("  ★ 随机初始密码（仅显示这一次，请立即保存）: %s" % password)
        elif created:
            print("  ★ 已使用 ADMIN_PASSWORD 指定的密码")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())