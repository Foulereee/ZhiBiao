from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from services.database import get_db
from services.models import (
    User,
    RBACRole,
    RBACPermission,
    RBACUserRole,
    RBACRolePermission,
)

router = APIRouter()


class RoleCreate(BaseModel):
    name: str
    display_name: str
    description: str = ""


class RoleUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None


class UserCreate(BaseModel):
    email: str
    name: str
    password: str = ""
    role_name: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    password: str | None = None


class PermissionAssign(BaseModel):
    permission_ids: list[str] = []


class RoleAssign(BaseModel):
    role_ids: list[str] = []


class PermissionCheck(BaseModel):
    user_id: str
    permission_code: str


DEFAULT_PERMISSIONS = {
    "project": [
        ("project.create", "创建项目"),
        ("project.read", "查看项目"),
        ("project.update", "更新项目"),
        ("project.delete", "删除项目"),
    ],
    "interpret": [
        ("interpret.upload", "上传招标文件"),
        ("interpret.parse", "解析招标文件"),
        ("interpret.view", "查看解读结果"),
    ],
    "generate": [
        ("generate.outline", "生成大纲"),
        ("generate.content", "生成正文"),
        ("generate.review", "审核内容"),
    ],
    "check": [
        ("check.run", "执行检查"),
        ("check.export", "导出检查结果"),
        ("check.report", "生成检查报告"),
    ],
    "format": [
        ("format.run", "执行格式化"),
        ("format.template", "管理模板"),
        ("format.config", "配置格式化"),
    ],
    "news": [
        ("news.monitor", "监控资讯"),
        ("news.view", "查看资讯"),
        ("news.manage", "管理资讯"),
    ],
    "knowledge": [
        ("knowledge.create", "创建知识库"),
        ("knowledge.upload", "上传知识文档"),
        ("knowledge.search", "搜索知识库"),
        ("knowledge.delete", "删除知识库"),
    ],
    "settings": [
        ("settings.view", "查看设置"),
        ("settings.llm", "配置LLM"),
        ("settings.agent", "配置Agent"),
        ("settings.rbac", "管理权限"),
    ],
}

DEFAULT_ROLES = {
    "admin": {
        "display_name": "管理员",
        "is_system": True,
        "permissions": "ALL",
    },
    "project_manager": {
        "display_name": "项目经理",
        "is_system": False,
        "excluded": ["settings.rbac", "settings.agent"],
    },
    "writer": {
        "display_name": "撰写员",
        "is_system": False,
        "permissions": [
            "project.create", "project.read", "project.update",
            "interpret.upload", "interpret.parse", "interpret.view",
            "generate.outline", "generate.content", "generate.review",
            "check.run", "check.export",
            "format.run",
            "knowledge.search",
        ],
    },
    "reviewer": {
        "display_name": "审核员",
        "is_system": False,
        "permissions": [
            "project.read",
            "interpret.view",
            "generate.review",
            "check.run", "check.export", "check.report",
            "format.run",
        ],
    },
}


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


@router.get("/roles")
async def list_roles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RBACRole).order_by(RBACRole.created_at))
    roles = result.scalars().all()

    rp_result = await db.execute(select(RBACRolePermission))
    rp_rows = rp_result.scalars().all()

    perm_result = await db.execute(select(RBACPermission))
    perm_rows = perm_result.scalars().all()
    perm_map = {str(p.id): p for p in perm_rows}

    role_perms: dict[str, list[dict]] = defaultdict(list)
    for rp in rp_rows:
        p = perm_map.get(str(rp.permission_id))
        if p:
            role_perms[str(rp.role_id)].append({
                "id": str(p.id),
                "code": p.code,
                "name": p.name,
                "category": p.category,
            })

    return {
        "roles": [
            {
                "id": str(r.id),
                "name": r.name,
                "display_name": r.display_name,
                "description": r.description,
                "is_system": r.is_system,
                "permissions": role_perms.get(str(r.id), []),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in roles
        ]
    }


@router.post("/roles")
async def create_role(data: RoleCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(RBACRole).where(RBACRole.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="角色名称已存在")

    role = RBACRole(
        name=data.name,
        display_name=data.display_name,
        description=data.description,
    )
    db.add(role)
    await db.flush()
    return {
        "id": str(role.id),
        "name": role.name,
        "display_name": role.display_name,
    }


@router.put("/roles/{role_id}")
async def update_role(
    role_id: str, data: RoleUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(RBACRole).where(RBACRole.id == uuid.UUID(role_id))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    if data.display_name is not None:
        role.display_name = data.display_name
    if data.description is not None:
        role.description = data.description
    await db.flush()

    return {
        "id": str(role.id),
        "name": role.name,
        "display_name": role.display_name,
        "description": role.description,
    }


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RBACRole).where(RBACRole.id == uuid.UUID(role_id))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_system:
        raise HTTPException(status_code=400, detail="系统角色不可删除")

    await db.execute(
        sa_delete(RBACRolePermission).where(
            RBACRolePermission.role_id == role.id
        )
    )
    await db.execute(
        sa_delete(RBACUserRole).where(RBACUserRole.role_id == role.id)
    )
    await db.delete(role)
    await db.flush()
    return {"success": True}


@router.get("/permissions")
async def list_permissions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RBACPermission).order_by(RBACPermission.category, RBACPermission.code)
    )
    perms = result.scalars().all()

    grouped: dict[str, list[dict]] = defaultdict(list)
    for p in perms:
        grouped[p.category].append({
            "id": str(p.id),
            "code": p.code,
            "name": p.name,
            "description": p.description,
        })

    return {"permissions": dict(grouped)}


@router.post("/roles/{role_id}/permissions")
async def assign_permissions(
    role_id: str, data: PermissionAssign, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(RBACRole).where(RBACRole.id == uuid.UUID(role_id))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    for pid_str in data.permission_ids:
        perm_result = await db.execute(
            select(RBACPermission).where(
                RBACPermission.id == uuid.UUID(pid_str)
            )
        )
        if not perm_result.scalar_one_or_none():
            continue

        existing = await db.execute(
            select(RBACRolePermission).where(
                RBACRolePermission.role_id == role.id,
                RBACRolePermission.permission_id == uuid.UUID(pid_str),
            )
        )
        if existing.scalar_one_or_none():
            continue

        db.add(
            RBACRolePermission(
                role_id=role.id,
                permission_id=uuid.UUID(pid_str),
            )
        )

    await db.flush()
    return {"success": True}


@router.delete("/roles/{role_id}/permissions/{permission_id}")
async def remove_permission(
    role_id: str, permission_id: str, db: AsyncSession = Depends(get_db)
):
    await db.execute(
        sa_delete(RBACRolePermission).where(
            RBACRolePermission.role_id == uuid.UUID(role_id),
            RBACRolePermission.permission_id == uuid.UUID(permission_id),
        )
    )
    await db.flush()
    return {"success": True}


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()

    ur_result = await db.execute(select(RBACUserRole))
    ur_rows = ur_result.scalars().all()

    role_result = await db.execute(select(RBACRole))
    role_rows = role_result.scalars().all()
    role_map = {str(r.id): r for r in role_rows}

    user_roles: dict[str, list[dict]] = defaultdict(list)
    for ur in ur_rows:
        r = role_map.get(str(ur.role_id))
        if r:
            user_roles[str(ur.user_id)].append({
                "id": str(r.id),
                "name": r.name,
                "display_name": r.display_name,
            })

    return {
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "name": u.name,
                "avatar": u.avatar,
                "roles": user_roles.get(str(u.id), []),
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    }


@router.post("/users")
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(User).where(User.email == data.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已存在")

    pw_hash = _hash_password(data.password) if data.password else None
    user = User(
        email=data.email,
        name=data.name,
        password_hash=pw_hash,
    )
    db.add(user)
    await db.flush()

    if data.role_name:
        role_result = await db.execute(
            select(RBACRole).where(RBACRole.name == data.role_name)
        )
        role = role_result.scalar_one_or_none()
        if role:
            db.add(RBACUserRole(user_id=user.id, role_id=role.id))
            await db.flush()

    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
    }


@router.put("/users/{user_id}")
async def update_user(
    user_id: str, data: UserUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if data.name is not None:
        user.name = data.name
    if data.email is not None:
        existing = await db.execute(
            select(User).where(User.email == data.email, User.id != user.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="邮箱已被使用")
        user.email = data.email
    if data.password is not None:
        user.password_hash = _hash_password(data.password)

    await db.flush()
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
    }


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await db.execute(
        sa_delete(RBACUserRole).where(
            RBACUserRole.user_id == user.id
        )
    )
    await db.delete(user)
    await db.flush()
    return {"success": True}


@router.post("/users/{user_id}/roles")
async def assign_roles(
    user_id: str, data: RoleAssign, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="用户不存在")

    for rid_str in data.role_ids:
        role_result = await db.execute(
            select(RBACRole).where(RBACRole.id == uuid.UUID(rid_str))
        )
        if not role_result.scalar_one_or_none():
            continue

        existing = await db.execute(
            select(RBACUserRole).where(
                RBACUserRole.user_id == uuid.UUID(user_id),
                RBACUserRole.role_id == uuid.UUID(rid_str),
            )
        )
        if existing.scalar_one_or_none():
            continue

        db.add(
            RBACUserRole(
                user_id=uuid.UUID(user_id),
                role_id=uuid.UUID(rid_str),
            )
        )

    await db.flush()
    return {"success": True}


@router.delete("/users/{user_id}/roles/{role_id}")
async def remove_role(
    user_id: str, role_id: str, db: AsyncSession = Depends(get_db)
):
    await db.execute(
        sa_delete(RBACUserRole).where(
            RBACUserRole.user_id == uuid.UUID(user_id),
            RBACUserRole.role_id == uuid.UUID(role_id),
        )
    )
    await db.flush()
    return {"success": True}


@router.post("/check-permission")
async def check_permission(
    data: PermissionCheck, db: AsyncSession = Depends(get_db)
):
    user_id = uuid.UUID(data.user_id)

    user_result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    perm_result = await db.execute(
        select(RBACPermission).where(RBACPermission.code == data.permission_code)
    )
    perm = perm_result.scalar_one_or_none()
    if not perm:
        return {"has_permission": False, "permission_code": data.permission_code}

    ur_result = await db.execute(
        select(RBACUserRole.role_id).where(RBACUserRole.user_id == user_id)
    )
    role_ids = [row[0] for row in ur_result.all()]

    if not role_ids:
        return {"has_permission": False, "permission_code": data.permission_code}

    rp_result = await db.execute(
        select(RBACRolePermission).where(
            RBACRolePermission.role_id.in_(role_ids),
            RBACRolePermission.permission_id == perm.id,
        )
    )
    has_perm = rp_result.scalar_one_or_none() is not None

    return {
        "has_permission": has_perm,
        "permission_code": data.permission_code,
    }


@router.post("/init")
async def init_rbac(db: AsyncSession = Depends(get_db)):
    perm_map: dict[str, uuid.UUID] = {}

    for category, perms in DEFAULT_PERMISSIONS.items():
        for code, name in perms:
            existing = await db.execute(
                select(RBACPermission).where(RBACPermission.code == code)
            )
            perm = existing.scalar_one_or_none()
            if perm:
                perm_map[code] = perm.id
            else:
                perm = RBACPermission(
                    code=code,
                    name=name,
                    category=category,
                )
                db.add(perm)
                await db.flush()
                perm_map[code] = perm.id

    all_perm_ids = list(perm_map.values())

    for role_name, role_def in DEFAULT_ROLES.items():
        existing = await db.execute(
            select(RBACRole).where(RBACRole.name == role_name)
        )
        role = existing.scalar_one_or_none()
        if not role:
            role = RBACRole(
                name=role_name,
                display_name=role_def["display_name"],
                is_system=role_def.get("is_system", False),
            )
            db.add(role)
            await db.flush()

        if role_def.get("permissions") == "ALL":
            target_perm_ids = all_perm_ids
        elif "excluded" in role_def:
            excluded_codes = set(role_def["excluded"])
            target_perm_ids = [
                pid for code, pid in perm_map.items()
                if code not in excluded_codes
            ]
        else:
            explicit_codes = role_def.get("permissions", [])
            target_perm_ids = [
                perm_map[code] for code in explicit_codes if code in perm_map
            ]

        for pid in target_perm_ids:
            existing_rp = await db.execute(
                select(RBACRolePermission).where(
                    RBACRolePermission.role_id == role.id,
                    RBACRolePermission.permission_id == pid,
                )
            )
            if not existing_rp.scalar_one_or_none():
                db.add(
                    RBACRolePermission(
                        role_id=role.id,
                        permission_id=pid,
                    )
                )

    await db.flush()

    return {
        "success": True,
        "message": "RBAC默认角色和权限初始化完成",
        "permissions_count": len(perm_map),
        "roles_count": len(DEFAULT_ROLES),
    }
