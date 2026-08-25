from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.skill_engine.registry import SkillRegistry
from core.skill_engine.base import SkillContext
from services.database import get_db
from services.llm_factory import get_llm_gateway
from services.middleware.rbac_middleware import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/")
async def list_skills():
    registry = SkillRegistry.instance()
    return {"skills": registry.list_all()}


@router.get("/{skill_name}")
async def get_skill_detail(skill_name: str):
    registry = SkillRegistry.instance()
    if not registry.has(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' 未找到")
    cls = registry.get(skill_name)
    return {
        "name": cls.name,
        "description": cls.description,
        "category": cls.category,
        "version": cls.version,
        "triggers": cls.triggers,
    }


@router.post("/{skill_name}/execute")
async def execute_skill(
    skill_name: str,
    parameters: dict,
    project_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    registry = SkillRegistry.instance()
    if not registry.has(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' 未找到")

    gateway = get_llm_gateway()
    skill_cls = registry.get(skill_name)
    skill = skill_cls()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters=parameters,
    )
    result = await skill.safe_execute(ctx)
    return {
        "success": result.success,
        "data": result.data,
        "error": result.error,
        "tokens_consumed": result.tokens_consumed,
        "warnings": result.warnings,
    }


@router.post("/reload")
async def reload_skills():
    from core.skill_engine.loader import SkillLoader
    from pathlib import Path

    loader = SkillLoader(Path("./skills"))
    loaded = loader.load_all()
    registry = SkillRegistry.instance()
    for name, info in loaded.items():
        try:
            cls = loader.get_skill_class(name)
            registry.register(cls)
        except Exception:
            continue
    return {"loaded_skills": list(loaded.keys())}
