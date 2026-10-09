from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.ocr import (
    get_mineru_client,
    reset_mineru_client_cache,
    MinerUError,
)
from core.settings import get_settings
from services.database import get_db
from services.llm_factory import get_llm_gateway
from core.skill_engine.base import SkillContext

from services.middleware.api_key import require_any_auth

router = APIRouter(dependencies=[Depends(require_any_auth)])

MAX_OCR_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB


class MinerUConfigPayload(BaseModel):
    mode: str = "cloud"
    api_key: str = ""
    endpoint: str = "https://mineru.net/api/v4"
    timeout: int = 180
    model_version: str = "vlm"
    poll_interval: int = 5
    max_polls: int = 60


def _env_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        ".env",
    )


def _persist_env(payload: MinerUConfigPayload) -> None:
    # 只替换这几个键，保留 .env 里原有的注释、分组与顺序。
    # 容器把宿主机的 .env bind mount 进来了，整文件重写会毁掉宿主机 .env 的注释。
    from core.env_store import update_env_keys

    updates: dict[str, str] = {
        "BMP_MINERU_MODE": payload.mode,
        "BMP_MINERU_ENDPOINT": payload.endpoint,
        "BMP_MINERU_TIMEOUT": str(payload.timeout),
        "BMP_MINERU_MODEL_VERSION": payload.model_version,
        "BMP_MINERU_POLL_INTERVAL": str(payload.poll_interval),
        "BMP_MINERU_MAX_POLLS": str(payload.max_polls),
    }
    if payload.api_key:
        updates["BMP_MINERU_API_KEY"] = payload.api_key

    update_env_keys(updates, path=_env_path())


@router.get("/config")
async def get_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "mode": settings.mineru_mode,
        "api_key_masked": _mask_key(settings.mineru_api_key),
        "endpoint": settings.mineru_endpoint,
        "timeout": settings.mineru_timeout,
        "model_version": settings.mineru_model_version,
        "poll_interval": settings.mineru_poll_interval,
        "max_polls": settings.mineru_max_polls,
    }


@router.put("/config")
async def update_config(payload: MinerUConfigPayload) -> dict[str, Any]:
    if payload.mode not in ("cloud", "self_hosted", "self-hosted", "selfhosted"):
        raise HTTPException(status_code=400, detail=f"不支持的 mode: {payload.mode}")
    settings = get_settings()
    effective_api_key = payload.api_key or settings.mineru_api_key
    if payload.mode == "cloud" and not effective_api_key:
        raise HTTPException(status_code=400, detail="云端模式必须填写 API Key（当前尚未配置）")
    if payload.mode in ("self_hosted", "self-hosted", "selfhosted") and not payload.endpoint:
        raise HTTPException(status_code=400, detail="自部署模式必须填写 endpoint")
    if payload.timeout < 10 or payload.timeout > 1800:
        raise HTTPException(status_code=400, detail="timeout 必须在 10-1800 秒之间")

    _persist_env(payload)
    reset_mineru_client_cache()

    return {
        "success": True,
        "config": {
            "mode": payload.mode,
            "api_key_masked": _mask_key(effective_api_key),
            "endpoint": payload.endpoint,
            "timeout": payload.timeout,
            "model_version": payload.model_version,
            "poll_interval": payload.poll_interval,
            "max_polls": payload.max_polls,
        },
    }


@router.post("/test")
async def test_connection(payload: MinerUConfigPayload) -> dict[str, Any]:
    try:
        client = get_mineru_client(
            mode=payload.mode,
            api_key=payload.api_key or None,
            endpoint=payload.endpoint,
            timeout=payload.timeout,
        )
    except MinerUError as e:
        return {"success": False, "error": str(e)}
    if payload.mode == "cloud":
        return await _test_cloud(client)
    return await _test_self_hosted(client)


async def _test_cloud(client: Any) -> dict[str, Any]:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=client.timeout) as c:
            resp = await c.get(
                f"{client.endpoint}/extract/task/healthcheck",
                headers=client._headers(),
            )
            if resp.status_code in (200, 201, 204, 404):
                return {"success": True, "message": f"云端连通正常 (HTTP {resp.status_code})"}
            return {"success": False, "error": f"云端返回 HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": f"云端连接失败: {e}"}


async def _test_self_hosted(client: Any) -> dict[str, Any]:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=client.timeout) as c:
            resp = await c.get(
                f"{client.endpoint}/health",
                headers=client._headers(),
            )
            if resp.status_code == 200:
                return {"success": True, "message": f"自部署服务健康检查通过 (HTTP {resp.status_code})"}
            return {"success": False, "error": f"自部署健康检查失败 HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": f"自部署连接失败: {e}"}


@router.post("/ocr")
async def ocr_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.mineru_api_key and (settings.mineru_mode or "cloud") == "cloud":
        raise HTTPException(status_code=400, detail="MinerU 尚未配置 API Key，请先在平台设置中完成配置")
    if not settings.mineru_endpoint:
        raise HTTPException(status_code=400, detail="MinerU 尚未配置 endpoint")

    upload_dir = Path("./uploads/mineru")
    upload_dir.mkdir(parents=True, exist_ok=True)
    # 文件名必须清洗：原来直接拼 file.filename，传入 "../../x" 可以写到 uploads 之外
    safe_name = re.sub(r"[^\w.\-]", "_", Path(file.filename or "upload").name) or "upload"
    file_path = upload_dir / safe_name
    # 先按 Content-Length 拦一道：否则 50MB 文件会先被完整读进内存才报错
    if file.size and file.size > MAX_OCR_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_OCR_UPLOAD_BYTES // 1024 // 1024}MB 上限",
        )
    content = await file.read()
    if len(content) > MAX_OCR_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_OCR_UPLOAD_BYTES // 1024 // 1024}MB 上限",
        )
    file_path.write_bytes(content)

    from services.format.skills.mineru_ocr_skill import MinerUOcrSkill

    gateway = get_llm_gateway()
    skill = MinerUOcrSkill()
    ctx = SkillContext(
        project_id="",
        db=db,
        llm=gateway,
        parameters={
            "file_path": str(file_path),
            "options": {
                "language": "ch",
                "enable_formula": True,
                "enable_table": True,
                "model_version": settings.mineru_model_version,
            },
        },
    )
    try:
        skill_result = await skill.safe_execute(ctx)
    finally:
        # OCR 用完即删：这个上传只为本次识别服务，不删会一直堆在 uploads/mineru 里
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
    if not skill_result.success:
        raise HTTPException(status_code=500, detail=skill_result.error or "OCR 抽取失败")
    return {"success": True, "data": skill_result.data}


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"
