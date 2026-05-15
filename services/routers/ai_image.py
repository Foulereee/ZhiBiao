from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.skill_engine.base import SkillContext
from services.generate.skills.ai_image_skill import AiImageSkill
from services.llm_factory import get_llm_gateway

router = APIRouter()

_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class ImageGenerateRequest(BaseModel):
    prompt: str
    provider: str = "fallback"
    image_size: str = "landscape_16_9"
    volcengine_api_key: str | None = None
    google_api_key: str | None = None


class ProviderConfig(BaseModel):
    volcengine_api_key: str | None = None
    google_api_key: str | None = None


@router.post("/generate")
async def generate_image(req: ImageGenerateRequest):
    skill = AiImageSkill()
    gateway = get_llm_gateway()

    parameters = {
        "prompt": req.prompt,
        "provider": req.provider,
        "image_size": req.image_size,
    }

    if req.volcengine_api_key:
        parameters["volcengine_api_key"] = req.volcengine_api_key
    elif req.provider == "volcengine":
        env_key = os.getenv("VOLCENGINE_API_KEY", "")
        if env_key:
            parameters["volcengine_api_key"] = env_key

    if req.google_api_key:
        parameters["google_api_key"] = req.google_api_key
    elif req.provider == "google":
        env_key = os.getenv("GOOGLE_API_KEY", "")
        if env_key:
            parameters["google_api_key"] = env_key

    ctx = SkillContext(
        project_id="",
        db=None,
        llm=gateway,
        parameters=parameters,
    )

    result = await skill.safe_execute(ctx)

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    return {"success": True, "data": result.data}


@router.get("/providers")
async def list_providers():
    volcengine_key = os.getenv("VOLCENGINE_API_KEY", "")
    google_key = os.getenv("GOOGLE_API_KEY", "")

    providers = [
        {
            "name": "volcengine",
            "display_name": "火山方舟",
            "configured": bool(volcengine_key),
            "description": "火山方舟视觉生成API",
        },
        {
            "name": "google",
            "display_name": "Google AI Studio (Imagen)",
            "configured": bool(google_key),
            "description": "Google Imagen 3.0 图片生成",
        },
        {
            "name": "fallback",
            "display_name": "默认服务",
            "configured": True,
            "description": "Trae text-to-image 免费服务",
        },
    ]

    return {"providers": providers}


@router.put("/config")
async def save_provider_config(config: ProviderConfig):
    lines: list[str] = []

    if _ENV_PATH.exists():
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    keys_to_set: dict[str, str | None] = {
        "VOLCENGINE_API_KEY": config.volcengine_api_key,
        "GOOGLE_API_KEY": config.google_api_key,
    }

    updated_keys: set[str] = set()

    for i, line in enumerate(lines):
        stripped = line.strip()
        for key, value in keys_to_set.items():
            if stripped.startswith(f"{key}="):
                if value is not None:
                    lines[i] = f"{key}={value}\n"
                else:
                    lines[i] = f"{key}=\n"
                updated_keys.add(key)
                break

    for key, value in keys_to_set.items():
        if key not in updated_keys:
            lines.append(f"{key}={value or ''}\n")

    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    if config.volcengine_api_key:
        os.environ["VOLCENGINE_API_KEY"] = config.volcengine_api_key
    if config.google_api_key:
        os.environ["GOOGLE_API_KEY"] = config.google_api_key

    return {
        "success": True,
        "message": "API配置已保存",
        "volcengine_configured": bool(config.volcengine_api_key),
        "google_configured": bool(config.google_api_key),
    }
