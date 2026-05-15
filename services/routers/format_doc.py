from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from services.database import get_db
from services.llm_factory import get_llm_gateway
from core.skill_engine.base import SkillContext

router = APIRouter()

UPLOAD_DIR = Path("./uploads/formatted")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATE_DIR = Path("./templates")
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/format")
async def format_document(
    file: UploadFile = File(...),
    template: str = "default",
    mode: str = Query("format", description="format|check|diff|beautify"),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    temp_path = UPLOAD_DIR / file.filename
    with open(temp_path, "wb") as f:
        f.write(content)

    from services.format.skills.docx_format_skill import DocxFormatSkill

    gateway = get_llm_gateway()
    skill = DocxFormatSkill()
    ctx = SkillContext(
        project_id="",
        db=db,
        llm=gateway,
        parameters={
            "file_path": str(temp_path),
            "template": template,
            "mode": mode,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success and skill_result.data:
        result_data = skill_result.data
        output_path = result_data.get("output_path", "")
        if output_path and Path(output_path).exists():
            result_data["file_name"] = Path(output_path).name

        return {
            "success": True,
            "data": result_data,
        }

    return {
        "success": False,
        "error": skill_result.error,
    }


@router.post("/check-format")
async def check_format(
    file: UploadFile = File(...),
    template: str = "default",
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    temp_path = UPLOAD_DIR / f"check_{file.filename}"
    with open(temp_path, "wb") as f:
        f.write(content)

    from services.format.skills.docx_format_skill import DocxFormatSkill

    gateway = get_llm_gateway()
    skill = DocxFormatSkill()
    ctx = SkillContext(
        project_id="",
        db=db,
        llm=gateway,
        parameters={
            "file_path": str(temp_path),
            "template": template,
            "mode": "check",
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        return {"success": True, "data": skill_result.data}

    return {"success": False, "error": skill_result.error}


@router.post("/diff-format")
async def diff_format(
    file: UploadFile = File(...),
    template: str = "default",
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    temp_path = UPLOAD_DIR / f"diff_{file.filename}"
    with open(temp_path, "wb") as f:
        f.write(content)

    from services.format.skills.docx_format_skill import DocxFormatSkill

    gateway = get_llm_gateway()
    skill = DocxFormatSkill()
    ctx = SkillContext(
        project_id="",
        db=db,
        llm=gateway,
        parameters={
            "file_path": str(temp_path),
            "template": template,
            "mode": "diff",
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        return {"success": True, "data": skill_result.data}

    return {"success": False, "error": skill_result.error}


@router.post("/beautify")
async def beautify_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    temp_path = UPLOAD_DIR / file.filename
    with open(temp_path, "wb") as f:
        f.write(content)

    from services.format.skills.docx_format_skill import DocxFormatSkill

    gateway = get_llm_gateway()
    skill = DocxFormatSkill()
    ctx = SkillContext(
        project_id="",
        db=db,
        llm=gateway,
        parameters={
            "file_path": str(temp_path),
            "mode": "beautify",
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success and skill_result.data:
        return {"success": True, "data": skill_result.data}

    return {"success": False, "error": skill_result.error}


@router.get("/templates")
async def list_templates():
    templates = [
        {"name": "default", "description": "默认标书排版模板(仿宋正文+黑体标题)"},
        {"name": "government", "description": "政府采购标书模板(方正小标宋+仿宋)"},
        {"name": "engineering", "description": "工程标书模板(宋体正文+黑体标题)"},
    ]

    for tpl_file in TEMPLATE_DIR.glob("*.yaml"):
        name = tpl_file.stem
        if not any(t["name"] == name for t in templates):
            templates.append({"name": name, "description": f"自定义模板: {name}"})

    return {"templates": templates}


@router.get("/templates/{template_name}")
async def get_template_detail(template_name: str):
    from services.format.skills.docx_format_skill import DEFAULT_FORMAT_CONFIG

    template_path = TEMPLATE_DIR / f"{template_name}.yaml"
    if template_path.exists():
        try:
            import yaml
            with open(template_path, encoding="utf-8") as f:
                custom_config = yaml.safe_load(f) or {}
            merged = {**DEFAULT_FORMAT_CONFIG, **custom_config}
        except Exception:
            merged = DEFAULT_FORMAT_CONFIG
    else:
        merged = DEFAULT_FORMAT_CONFIG

    return {"name": template_name, "config": merged}


@router.put("/templates/{template_name}")
async def save_template(template_name: str, config: dict):
    import yaml

    template_path = TEMPLATE_DIR / f"{template_name}.yaml"
    with open(template_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    return {"success": True, "name": template_name}


@router.delete("/templates/{template_name}")
async def delete_template(template_name: str):
    if template_name in ("default", "government", "engineering"):
        return {"success": False, "error": "内置模板不可删除"}

    template_path = TEMPLATE_DIR / f"{template_name}.yaml"
    if template_path.exists():
        template_path.unlink()
        return {"success": True}
    return {"success": False, "error": "模板不存在"}
