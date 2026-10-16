from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import Project, Document, Analysis, ProjectStatus, iso_utc
from services.llm_factory import get_llm_gateway
# 模块级导入：risk_alert() 与 export_interpret() 里原本只在别的函数内 import 过
# SkillContext，它们自己的函数体引用到它就抛 NameError（这两个接口一调就 500）。
from core.skill_engine.base import SkillContext

from services.middleware.api_key import require_any_auth

router = APIRouter(dependencies=[Depends(require_any_auth)])

MAX_FILE_SIZE = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".wps", ".md"}


def _merge_tables_into_content(parsed) -> str:
    """把解析出的表格内容并入正文文本。

    原先这里只落 `parsed.text`（纯段落），`parsed.tables` 仅用于返回一个
    tables_count 计数就丢弃了。而评分标准表、资格要求表这些决定评分的
    关键内容全在表格里 —— 丢掉之后「评分矩阵」只能靠编，「大纲对齐评分项」
    和「评分覆盖」自然全部落空。
    docx 解析器已按文档顺序把表格写进 text（metadata.tables_inlined=True），
    这里只对没有内联能力的解析器（如 pdf）做兜底合并。
    """
    text = getattr(parsed, "text", "") or ""
    tables = getattr(parsed, "tables", None) or []
    metadata = getattr(parsed, "metadata", None) or {}
    if not tables or metadata.get("tables_inlined"):
        return text

    parts = [text, "\n\n【表格内容】"]
    for i, table in enumerate(tables):
        rows = table.get("rows") if isinstance(table, dict) else None
        headers = table.get("headers") if isinstance(table, dict) else None
        parts.append(f"【表{i}】")
        if headers:
            parts.append(" | ".join(str(h).replace("\n", " ").strip() for h in headers))
        for row in rows or []:
            if isinstance(row, (list, tuple)):
                parts.append(" | ".join(str(c).replace("\n", " ").strip() for c in row))
            else:
                parts.append(str(row))
    return "\n".join(parts)


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

        # 先按 Content-Length 拦一道：否则 100MB 文件会先被完整读进内存才报错
        if file.size and file.size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制({MAX_FILE_SIZE // 1024 // 1024}MB)")

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制({MAX_FILE_SIZE // 1024 // 1024}MB)")

        # 文件名清洗：原来直接拼 file.filename，传 "../../x" 可写到项目目录之外。
        # 招标文件要长期保留（数据库存的是这个路径，后续解析还要读），所以不删文件。
        safe_name = re.sub(r"[^\w.\-]", "_", Path(file.filename or "upload").name) or "upload"
        file_path = upload_dir / safe_name
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
            "created_at": iso_utc(d.created_at),
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
        "created_at": iso_utc(doc.created_at),
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

    parsed_text = _merge_tables_into_content(parsed)
    doc.parsed_content = parsed_text
    metadata = dict(parsed.metadata or {})
    metadata["content_chars"] = len(parsed_text)
    metadata["tables_persisted"] = True
    doc.doc_metadata = metadata
    project.status = ProjectStatus.INTERPRETING.value
    await db.flush()

    detector = SectionDetector(llm_gateway=get_llm_gateway())
    sections = await detector.detect_async(parsed_text)

    return {
        "project_id": project_id,
        "text_length": len(parsed_text),
        "tables_count": len(parsed.tables),
        "sections_count": len(sections),
        "sections": sections,
        "doc_metadata": metadata,
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
        # 金额大小写对齐：解读模型实测把"投标保证金捌万元整"记成"（80.00元）"，
        # 少了一万倍。大写金额是法律有效表述，以小写为准去改是错的，必须反过来。
        try:
            from services.generate.skills.norm_rules import fix_cn_amounts_in
            _dims = fix_cn_amounts_in(skill_result.data.get("dimensions", {}) or {})
            _sms = fix_cn_amounts_in(skill_result.data.get("scoring_matrix", {}) or {})
            _secs = fix_cn_amounts_in(skill_result.data.get("sections", []) or [])
        except Exception:
            _dims = skill_result.data.get("dimensions", {})
            _sms = skill_result.data.get("scoring_matrix", {})
            _secs = skill_result.data.get("sections", [])
        if analysis:
            analysis.dimensions = _dims
            analysis.scoring_matrix = _sms
            analysis.risk_flags = skill_result.data.get("risk_flags", {})
            analysis.sections = _secs
        else:
            analysis = Analysis(
                project_id=project.id,
                dimensions=_dims,
                scoring_matrix=_sms,
                risk_flags=skill_result.data.get("risk_flags", {}),
                sections=_secs,
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
    # 解读阶段可能没提取到评分项:把招标文件原文一并传入,让技能能从原文回退构建
    from services.models import Document as _DocModel

    doc_result = await db.execute(
        select(_DocModel)
        .where(_DocModel.project_id == project_id)
        .order_by(_DocModel.created_at.asc())
    )
    doc = doc_result.scalars().first()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "scoring_data": analysis.dimensions.get("scoring", {}),
            "document_text": (getattr(doc, "parsed_content", "") or "") if doc else "",
        },
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
