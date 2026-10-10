"""品牌名配置接口。

全站所有出现产品名的地方（浏览器标题、登录页、侧边栏、FastAPI 文档标题、
健康检查、导出报告落款、MCP server 名、docx 修订作者、抓取 UA）都统一读
`core.settings.Settings` 里的 app_name / app_tagline / app_version。
这三个值来自 `.env`：

    BMP_APP_NAME=智标
    BMP_APP_TAGLINE=全流程智能招投标平台
    BMP_APP_VERSION=2.0

于是「改名字」只需要改一个地方。本接口就是把这件事变成一次 HTTP 调用：

    GET  /api/app-config/config   —— 公开。前端在**未登录的登录页**就要显示
                                     品牌名，所以不能加鉴权。
    PUT  /api/app-config/config   —— 需要登录。写入宿主机 .env 并热重载，
                                     立即生效，不需要重建容器，也不需要重新
                                     构建前端（前端是运行时拉取的）。

注意：容器里的 `/app/.env` 是**宿主机仓库根目录 `.env`** 的 bind mount
（见 docker-compose 的 x-api-volumes）。没有这个挂载，写入只会落在容器内
一个随容器销毁的文件上，改了等于没改。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from core.env_store import env_path, project_root, update_env_keys
from core.settings import env_file_path, env_file_stamp, get_settings, reload_settings
from services.middleware.rbac_middleware import get_current_user
from services.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FIELD_LEN = 80

# 字段名 → .env 里的键（pydantic Settings 前缀是 BMP_）
_ENV_KEYS: dict[str, str] = {
    "name": "BMP_APP_NAME",
    "tagline": "BMP_APP_TAGLINE",
    "version": "BMP_APP_VERSION",
}

_FIELD_LABELS: dict[str, str] = {
    "name": "产品名",
    "tagline": "副标题",
    "version": "版本号",
}


class AppConfigPayload(BaseModel):
    name: str | None = None
    tagline: str | None = None
    version: str | None = None


def _current() -> dict[str, str]:
    s = get_settings()
    return {
        "name": s.app_name,
        "tagline": s.app_tagline,
        "version": s.app_version,
    }


def _env_debug() -> dict[str, Any]:
    """报告**本进程当前看到的** .env 状态。

    排查「.env 改了不生效」时用它：拿这里的 inode / mtime 跟宿主机上
    `stat -c '%i %y' <宿主机仓库根目录>/.env` 对一下。

    - inode 不一样  → 踩到了单文件 bind mount 的坑（宿主机用 sed -i 之类
      「原子替换」方式改的，容器挂载点还指着旧 inode）。此时**必须重建容器**：
      `docker compose -f docker/docker-compose.yml --profile infra up -d --no-deps api celery-worker celery-beat`
    - inode 一样但 mtime 更旧 → 容器读到的还是旧内容，同样重建容器。
    - 都一样但 name 没变 → 那是 Settings 缓存的问题（本版本已修，会自动重载）。
    """
    info: dict[str, Any] = {"path": env_file_path()}
    stamp = env_file_stamp()
    if stamp is None:
        info["exists"] = False
        return info
    info["exists"] = True
    info["mtime_ns"], info["size"], info["inode"] = stamp
    info["hint"] = "把 inode/mtime_ns 与宿主机 stat -c '%i %Y' <仓库根目录>/.env 对比；不一致即为挂载点过期，需重建容器"
    return info


@router.get("/config")
async def read_app_config(response: Response) -> dict[str, Any]:
    """公开读取当前品牌信息（登录页就要用，不能加鉴权）。"""
    # 前端会在页面重新可见时再拉一次，这里禁止任何中间层缓存，
    # 否则改完名字刷新页面还可能拿到旧值。
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "success": True,
        **_current(),
        "env_file": env_path(),
        "env_keys": dict(_ENV_KEYS),
        "env_debug": _env_debug(),
    }


@router.put("/config")
async def update_app_config(
    payload: AppConfigPayload,
    response: Response,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """修改品牌信息：写回 .env 并热重载，立即生效。

    只传需要改的字段即可，例如 {"name": "智标云"}。
    """
    updates: dict[str, str] = {}
    for field, env_key in _ENV_KEYS.items():
        raw = getattr(payload, field)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            raise HTTPException(
                status_code=400,
                detail=f"{_FIELD_LABELS[field]}不能为空；如不需要修改请不要传该字段",
            )
        if len(value) > MAX_FIELD_LEN:
            raise HTTPException(
                status_code=400,
                detail=f"{_FIELD_LABELS[field]}长度不能超过 {MAX_FIELD_LEN} 个字符",
            )
        updates[env_key] = value

    if not updates:
        raise HTTPException(
            status_code=400,
            detail=f"没有需要修改的字段，可选：{'、'.join(_ENV_KEYS)}",
        )

    before = _current()
    try:
        write_result = update_env_keys(updates)
    except OSError as e:
        # 最常见原因：容器里没有挂载 .env（只读文件系统 / 无写权限）
        raise HTTPException(
            status_code=500,
            detail=(
                f"写入 {env_path()} 失败: {e}。"
                "请确认 docker-compose 已把 ../.env 挂载进容器且文件可写。"
            ),
        )

    reload_settings()
    after = _current()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    logger.info(
        "[品牌配置] %s 由 %s 修改: %s -> %s",
        user.email, write_result.get("path"), before, after,
    )

    return {
        "success": True,
        "before": before,
        "after": after,
        "env_file": write_result.get("path"),
        "updated": write_result.get("updated"),
        "added": write_result.get("added"),
        "backup": write_result.get("backup"),
        "project_root": project_root(),
        "note": "已热重载，前端刷新页面即可看到新名字（无需重建容器或前端）",
    }