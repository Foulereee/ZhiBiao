from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import Project, Document, Analysis, ProjectStatus
from services.llm_factory import get_llm_gateway

router = APIRouter()

MAX_FILE_SIZE = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".wps", ".md"}


@router.post("/upload/{project_id}")
async def upload_tender_file(
    project_id: str,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    upload_dir = Path(f"./projects/{project_id}")
    upload_dir.mkdir(parents=True, exist_ok=True)

    uploaded = []
    for file in files:
        file_ext = Path(file.filename).suffix.lower() if file.filename else ""
        if file_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件格式: {file_ext}")

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制({MAX_FILE_SIZE // 1024 // 1024}MB)")

        file_path = upload_dir / file.filename
        with open(file_path, "wb") as f:
            f.write(content)

        doc = Document(
            project_id=project.id,
            type="tender",
            file_path=str(file_path),
            original_name=file.filename,
            file_size=len(content),
        )
        db.add(doc)
        await db.flush()

        if not project.tender_doc_id:
            project.tender_doc_id = doc.id
            await db.flush()

        uploaded.append({
            "document_id": str(doc.id),
            "file_name": file.filename,
            "file_size": len(content),
        })

    return {"uploaded": uploaded, "total": len(uploaded)}


@router.get("/documents/{project_id}")
async def list_documents(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Document).where(Document.project_id == project_id).order_by(Document.created_at)
    )
    docs = result.scalars().all()
    return {"documents": [
        {
            "id": str(d.id),
            "file_name": d.original_name,
            "file_size": d.file_size,
            "type": d.type,
            "parsed": d.parsed_content is not None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]}


@router.get("/document/{document_id}")
async def get_document_content(document_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    content_preview = None
    if doc.parsed_content:
        content_preview = doc.parsed_content[:50000]

    return {
        "id": str(doc.id),
        "file_name": doc.original_name,
        "file_size": doc.file_size,
        "type": doc.type,
        "parsed_content": content_preview,
        "doc_metadata": doc.doc_metadata,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.post("/parse/{project_id}")
async def parse_tender_file(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="招标文件未上传")

    from core.doc_engine import get_parser, SectionDetector
    from pathlib import Path
    file_ext = Path(doc.file_path).suffix
    try:
        parser = get_parser(file_ext)
        parsed = parser.parse(doc.file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件解析失败: {e}")

    doc.parsed_content = parsed.text
    doc.doc_metadata = parsed.metadata
    project.status = ProjectStatus.INTERPRETING.value
    await db.flush()

    detector = SectionDetector(llm_gateway=get_llm_gateway())
    sections = await detector.detect_async(parsed.text)

    return {
        "project_id": project_id,
        "text_length": len(parsed.text),
        "tables_count": len(parsed.tables),
        "sections_count": len(sections),
        "sections": sections,
        "doc_metadata": parsed.metadata,
    }


@router.get("/analysis/{project_id}")
async def get_analysis(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()

    has_documents = False
    doc_list_result = await db.execute(
        select(Document).where(Document.project_id == project.id).order_by(Document.created_at)
    )
    doc_list = doc_list_result.scalars().all()
    has_documents = len(doc_list) > 0
    has_parsed = any(d.parsed_content is not None for d in doc_list)

    return {
        "has_documents": has_documents,
        "has_parsed": has_parsed,
        "has_analysis": analysis is not None and analysis.dimensions is not None,
        "analysis": {
            "dimensions": analysis.dimensions if analysis else None,
            "scoring_matrix": analysis.scoring_matrix if analysis else None,
            "risk_flags": analysis.risk_flags if analysis else None,
            "sections": analysis.sections if analysis else None,
        } if analysis else None,
        "parse_info": {
            "text_length": len(doc.parsed_content) if doc and doc.parsed_content else 0,
            "doc_metadata": doc.doc_metadata if doc else None,
        } if doc and doc.parsed_content else None,
    }


@router.post("/interpret/{project_id}")
async def interpret_tender(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc or not doc.parsed_content:
        raise HTTPException(status_code=400, detail="请先解析招标文件")

    from services.interpret.skills.tender_interpret_skill import TenderInterpretSkill
    from core.skill_engine.base import SkillContext

    gateway = get_llm_gateway()
    skill = TenderInterpretSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={"document_text": doc.parsed_content},
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        existing = await db.execute(
            select(Analysis).where(Analysis.project_id == project.id)
        )
        analysis = existing.scalar_one_or_none()
        if analysis:
            analysis.dimensions = skill_result.data.get("dimensions", {})
            analysis.scoring_matrix = skill_result.data.get("scoring_matrix", {})
            analysis.risk_flags = skill_result.data.get("risk_flags", {})
            analysis.sections = skill_result.data.get("sections", [])
        else:
            analysis = Analysis(
                project_id=project.id,
                dimensions=skill_result.data.get("dimensions", {}),
                scoring_matrix=skill_result.data.get("scoring_matrix", {}),
                risk_flags=skill_result.data.get("risk_flags", {}),
                sections=skill_result.data.get("sections", []),
            )
            db.add(analysis)
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.post("/scoring-matrix/{project_id}")
async def build_scoring_matrix(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    if not analysis or not analysis.dimensions:
        raise HTTPException(status_code=400, detail="请先完成招标解读")

    from services.interpret.skills.scoring_matrix_skill import ScoringMatrixSkill
    from core.skill_engine.base import SkillContext

    gateway = get_llm_gateway()
    skill = ScoringMatrixSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={"scoring_data": analysis.dimensions.get("scoring", {})},
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success and analysis:
        analysis.scoring_matrix = skill_result.data
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
    }


@router.post("/risk-alert/{project_id}")
async def risk_alert(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc or not doc.parsed_content:
        raise HTTPException(status_code=400, detail="请先上传招标文件")

    from services.interpret.skills.risk_alert_skill import RiskAlertSkill

    gateway = get_llm_gateway()
    skill = RiskAlertSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={"tender_text": doc.parsed_content[:6000]},
    )
    skill_result = await skill.safe_execute(ctx)

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
    }


@router.post("/export/{project_id}")
async def export_interpret(
    project_id: str,
    format: str = "markdown",
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import PlainTextResponse

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    if not analysis or not analysis.dimensions:
        raise HTTPException(status_code=400, detail="请先完成招标解读")

    from services.interpret.skills.interpret_export_skill import InterpretExportSkill

    gateway = get_llm_gateway()
    skill = InterpretExportSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "interpret_data": analysis.dimensions,
            "format": format,
            "project_name": project.name,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if not skill_result.success:
        raise HTTPException(status_code=500, detail=skill_result.error)

    content = skill_result.data.get("content", "")
    content_type = "text/markdown" if format == "markdown" else "text/html" if format == "html" else "application/json"
    return PlainTextResponse(content=content, media_type=content_type)
