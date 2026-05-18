from __future__ import annotations

import tempfile
import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import (
    Project, Document, Analysis, Chapter, CheckReport,
    ProjectStatus, CheckType,
)
from services.llm_factory import get_llm_gateway
from core.skill_engine.base import SkillContext

router = APIRouter()


async def _get_tender_and_bid_text(project_id: str, db: AsyncSession):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    tender_text = ""
    if project.tender_doc_id:
        doc_result = await db.execute(
            select(Document).where(Document.id == project.tender_doc_id)
        )
        doc = doc_result.scalar_one_or_none()
        if doc and doc.parsed_content:
            tender_text = doc.parsed_content

    bid_docs = await db.execute(
        select(Document).where(
            Document.project_id == project.id,
            Document.type == "bid",
        )
    )
    bid_doc = bid_docs.scalars().first()
    bid_text = bid_doc.parsed_content if bid_doc and bid_doc.parsed_content else ""

    if not bid_text:
        chapter_result = await db.execute(
            select(Chapter).where(Chapter.project_id == project.id)
        )
        chapters = chapter_result.scalars().all()
        if chapters:
            bid_text = "\n\n".join(
                f"## {ch.title}\n{ch.content or ''}" for ch in chapters if ch.content
            )

    return project, tender_text, bid_text


@router.post("/{project_id}/compliance")
async def check_compliance(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

    if not tender_text or not bid_text:
        raise HTTPException(status_code=400, detail="招标文件或投标文件内容为空")

    from services.check.skills.compliance_check_skill import ComplianceCheckSkill

    gateway = get_llm_gateway()
    skill = ComplianceCheckSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={"tender_text": tender_text, "bid_text": bid_text},
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        report = CheckReport(
            project_id=project.id,
            type=CheckType.COMPLIANCE,
            results=skill_result.data,
            risk_level="high" if skill_result.data.get("has_critical_issues") else "low",
            summary={
                "total": skill_result.data.get("total_requirements", 0),
                "compliant": skill_result.data.get("compliant", 0),
                "non_compliant": skill_result.data.get("non_compliant", 0),
            },
        )
        db.add(report)
        project.status = ProjectStatus.CHECKING
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.post("/{project_id}/disqualification")
async def check_disqualification(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

    if not tender_text or not bid_text:
        raise HTTPException(status_code=400, detail="招标文件或投标文件内容为空")

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    dq_clauses = []
    if analysis and analysis.dimensions:
        dq_data = analysis.dimensions.get("disqualification", {})
        if dq_data and not dq_data.get("error"):
            dq_clauses = dq_data.get("clauses", [])

    from services.check.skills.disqualification_check_skill import DisqualificationCheckSkill

    gateway = get_llm_gateway()
    skill = DisqualificationCheckSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "tender_text": tender_text,
            "bid_text": bid_text,
            "disqualification_clauses": dq_clauses,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        report = CheckReport(
            project_id=project.id,
            type=CheckType.DISQUALIFICATION,
            results=skill_result.data,
            risk_level="high" if skill_result.data.get("missing", 0) > 0 else "low",
        )
        db.add(report)
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.post("/{project_id}/qualification")
async def check_qualification(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

    from services.check.skills.qualification_check_skill import QualificationCheckSkill

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    timeline = analysis.dimensions.get("timeline", {}) if analysis and analysis.dimensions else {}
    bid_deadline = timeline.get("投标截止日", "") if isinstance(timeline, dict) else ""

    gateway = get_llm_gateway()
    skill = QualificationCheckSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "tender_text": tender_text,
            "bid_text": bid_text,
            "bid_deadline": bid_deadline,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        report = CheckReport(
            project_id=project.id,
            type=CheckType.QUALIFICATION,
            results=skill_result.data,
            risk_level=skill_result.data.get("risk_level", "low"),
        )
        db.add(report)
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.post("/{project_id}/pricing")
async def check_pricing(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    max_price = None
    if analysis and analysis.dimensions:
        project_info = analysis.dimensions.get("project_info", {})
        if isinstance(project_info, dict):
            budget_str = project_info.get("预算金额", "")
            if budget_str:
                import re
                match = re.search(r"[\d.]+", str(budget_str))
                if match:
                    max_price = float(match.group())

    from services.check.skills.pricing_check_skill import PricingCheckSkill

    gateway = get_llm_gateway()
    skill = PricingCheckSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "tender_text": tender_text,
            "bid_text": bid_text,
            "max_price": max_price,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        report = CheckReport(
            project_id=project.id,
            type=CheckType.PRICING,
            results=skill_result.data,
            risk_level=skill_result.data.get("risk_level", "low"),
        )
        db.add(report)
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.post("/{project_id}/fit-score")
async def check_fit_score(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

    if not tender_text or not bid_text:
        raise HTTPException(status_code=400, detail="招标文件或投标文件内容为空")

    from services.check.skills.fit_score_skill import FitScoreSkill

    gateway = get_llm_gateway()
    skill = FitScoreSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={"tender_text": tender_text, "bid_text": bid_text},
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        report = CheckReport(
            project_id=project.id,
            type=CheckType.FIT_SCORE,
            results=skill_result.data,
        )
        db.add(report)
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.post("/{project_id}/selfcheck")
async def run_selfcheck(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

    check_results = {}

    if tender_text and bid_text:
        gateway = get_llm_gateway()

        from services.check.skills.compliance_check_skill import ComplianceCheckSkill
        compliance_skill = ComplianceCheckSkill()
        compliance_ctx = SkillContext(
            project_id=project_id, db=db, llm=gateway,
            parameters={"tender_text": tender_text, "bid_text": bid_text},
        )
        compliance_result = await compliance_skill.safe_execute(compliance_ctx)
        if compliance_result.success:
            check_results["compliance_check"] = compliance_result.data

        from services.check.skills.pricing_check_skill import PricingCheckSkill
        pricing_skill = PricingCheckSkill()
        pricing_ctx = SkillContext(
            project_id=project_id, db=db, llm=gateway,
            parameters={"tender_text": tender_text, "bid_text": bid_text},
        )
        pricing_result = await pricing_skill.safe_execute(pricing_ctx)
        if pricing_result.success:
            check_results["pricing_check"] = pricing_result.data

        from services.check.skills.qualification_check_skill import QualificationCheckSkill
        qual_skill = QualificationCheckSkill()
        qual_ctx = SkillContext(
            project_id=project_id, db=db, llm=gateway,
            parameters={"tender_text": tender_text, "bid_text": bid_text},
        )
        qual_result = await qual_skill.safe_execute(qual_ctx)
        if qual_result.success:
            check_results["qualification_check"] = qual_result.data

    from services.check.skills.selfcheck_list_skill import SelfcheckListSkill

    skill = SelfcheckListSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=get_llm_gateway(),
        parameters={"check_results": check_results},
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        report = CheckReport(
            project_id=project.id,
            type=CheckType.SELFCHECK,
            results=skill_result.data,
            risk_level="low" if skill_result.data.get("can_submit") else "high",
        )
        db.add(report)
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.post("/{project_id}/full-check")
async def full_check(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

    if not tender_text or not bid_text:
        raise HTTPException(status_code=400, detail="招标文件或投标文件内容为空")

    gateway = get_llm_gateway()
    all_results = {}

    from services.check.skills.compliance_check_skill import ComplianceCheckSkill
    compliance_skill = ComplianceCheckSkill()
    compliance_ctx = SkillContext(
        project_id=project_id, db=db, llm=gateway,
        parameters={"tender_text": tender_text, "bid_text": bid_text},
    )
    compliance_result = await compliance_skill.safe_execute(compliance_ctx)
    all_results["compliance"] = {"success": compliance_result.success, "data": compliance_result.data}

    from services.check.skills.disqualification_check_skill import DisqualificationCheckSkill
    dq_skill = DisqualificationCheckSkill()
    dq_ctx = SkillContext(
        project_id=project_id, db=db, llm=gateway,
        parameters={"tender_text": tender_text, "bid_text": bid_text},
    )
    dq_result = await dq_skill.safe_execute(dq_ctx)
    all_results["disqualification"] = {"success": dq_result.success, "data": dq_result.data}

    from services.check.skills.qualification_check_skill import QualificationCheckSkill
    qual_skill = QualificationCheckSkill()
    qual_ctx = SkillContext(
        project_id=project_id, db=db, llm=gateway,
        parameters={"tender_text": tender_text, "bid_text": bid_text},
    )
    qual_result = await qual_skill.safe_execute(qual_ctx)
    all_results["qualification"] = {"success": qual_result.success, "data": qual_result.data}

    from services.check.skills.pricing_check_skill import PricingCheckSkill
    pricing_skill = PricingCheckSkill()
    pricing_ctx = SkillContext(
        project_id=project_id, db=db, llm=gateway,
        parameters={"tender_text": tender_text, "bid_text": bid_text},
    )
    pricing_result = await pricing_skill.safe_execute(pricing_ctx)
    all_results["pricing"] = {"success": pricing_result.success, "data": pricing_result.data}

    from services.check.skills.fit_score_skill import FitScoreSkill
    fit_skill = FitScoreSkill()
    fit_ctx = SkillContext(
        project_id=project_id, db=db, llm=gateway,
        parameters={"tender_text": tender_text, "bid_text": bid_text},
    )
    fit_result = await fit_skill.safe_execute(fit_ctx)
    all_results["fit_score"] = {"success": fit_result.success, "data": fit_result.data}

    has_critical = any(
        r["data"].get("has_critical_issues") or r["data"].get("risk_level") == "high"
        for r in all_results.values()
        if r["success"] and isinstance(r["data"], dict)
    )

    report = CheckReport(
        project_id=project.id,
        type=CheckType.SELFCHECK,
        results=all_results,
        risk_level="high" if has_critical else "low",
        summary={"checks_run": len(all_results), "has_critical": has_critical},
    )
    db.add(report)
    project.status = ProjectStatus.CHECKING
    await db.flush()

    return {
        "success": True,
        "data": all_results,
        "has_critical": has_critical,
    }


@router.get("/{project_id}/reports")
async def list_check_reports(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    reports_result = await db.execute(
        select(CheckReport).where(CheckReport.project_id == project.id)
    )
    reports = reports_result.scalars().all()

    return {"reports": [
        {
            "id": str(r.id),
            "type": r.type.value if isinstance(r.type, CheckType) else r.type,
            "risk_level": r.risk_level,
            "summary": r.summary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reports
    ]}


@router.post("/{project_id}/deposit")
async def check_deposit(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.deposit_check_skill import DepositCheckSkill
    gateway = get_llm_gateway()
    skill = DepositCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.DEPOSIT, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


async def _parse_uploaded_file(file: UploadFile) -> str:
    suffix = os.path.splitext(file.filename or "")[1].lower()
    content_bytes = await file.read()

    if suffix == ".txt" or suffix == ".md":
        return content_bytes.decode("utf-8", errors="replace")

    if suffix == ".docx":
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                tmp.write(content_bytes)
                tmp_path = tmp.name

            from docx import Document as DocxDocument
            doc = DocxDocument(tmp_path)
            paragraphs = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    style_name = (para.style.name or "").lower() if para.style else ""
                    if "heading" in style_name or "标题" in style_name:
                        level = "1"
                        for ch in style_name:
                            if ch.isdigit():
                                level = ch
                                break
                        paragraphs.append(f"{'#' * int(level)} {text}")
                    else:
                        paragraphs.append(text)

            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        paragraphs.append(" | ".join(cells))

            return "\n\n".join(paragraphs)
        except Exception as e:
            return content_bytes.decode("utf-8", errors="replace")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    if suffix == ".pdf":
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(content_bytes)
                tmp_path = tmp.name

            try:
                import pdfplumber
                texts = []
                with pdfplumber.open(tmp_path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            texts.append(page_text)
                return "\n\n".join(texts)
            except ImportError:
                pass

            try:
                import fitz
                doc = fitz.open(tmp_path)
                texts = []
                for page in doc:
                    texts.append(page.get_text())
                doc.close()
                return "\n\n".join(texts)
            except ImportError:
                pass

            return content_bytes.decode("utf-8", errors="replace")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    return content_bytes.decode("utf-8", errors="replace")


_CHECK_SKILL_MAP = {
    "compliance": ("services.check.skills.compliance_check_skill", "ComplianceCheckSkill"),
    "disqualification": ("services.check.skills.disqualification_check_skill", "DisqualificationCheckSkill"),
    "qualification": ("services.check.skills.qualification_check_skill", "QualificationCheckSkill"),
    "pricing": ("services.check.skills.pricing_check_skill", "PricingCheckSkill"),
    "fitScore": ("services.check.skills.fit_score_skill", "FitScoreSkill"),
    "deposit": ("services.check.skills.deposit_check_skill", "DepositCheckSkill"),
    "signature": ("services.check.skills.signature_check_skill", "SignatureCheckSkill"),
    "validity": ("services.check.skills.validity_check_skill", "ValidityCheckSkill"),
    "consistency": ("services.check.skills.consistency_check_skill", "ConsistencyCheckSkill"),
    "duplicate": ("services.check.skills.duplicate_check_skill", "DuplicateCheckSkill"),
    "mandatoryReq": ("services.check.skills.mandatory_req_check_skill", "MandatoryReqCheckSkill"),
    "docIntegrity": ("services.check.skills.doc_integrity_check_skill", "DocIntegrityCheckSkill"),
    "aiTextCheck": ("services.check.skills.ai_text_check_skill", "AITextCheckSkill"),
    "riskScore": ("services.check.skills.risk_score_skill", "RiskScoreSkill"),
    "crossCheck": ("services.check.skills.cross_check_skill", "CrossCheckSkill"),
    "sampleReport": ("services.check.skills.sample_report_check_skill", "SampleReportCheckSkill"),
    "jointBid": ("services.check.skills.joint_bid_check_skill", "JointBidCheckSkill"),
    "ebidSubmit": ("services.check.skills.ebid_submit_check_skill", "EbidSubmitCheckSkill"),
    "pricingLogic": ("services.check.skills.pricing_logic_check_skill", "PricingLogicCheckSkill"),
}


@router.post("/upload-check")
async def upload_and_check(
    bid_file: UploadFile = File(..., description="投标文件(.docx/.pdf/.txt)"),
    tender_file: UploadFile | None = File(None, description="招标文件(可选，.docx/.pdf/.txt)"),
    check_type: str = Form("fullCheck", description="检查类型: fullCheck/compliance/disqualification/..."),
    db: AsyncSession = Depends(get_db),
):
    bid_text = await _parse_uploaded_file(bid_file)
    if not bid_text.strip():
        raise HTTPException(status_code=400, detail="投标文件内容为空或无法解析")

    tender_text = ""
    if tender_file:
        tender_text = await _parse_uploaded_file(tender_file)

    gateway = get_llm_gateway()

    if check_type == "fullCheck":
        all_results = {}
        check_types = [
            "compliance", "disqualification", "qualification", "pricing",
            "fitScore", "deposit", "signature", "validity",
            "consistency", "duplicate", "mandatoryReq", "docIntegrity",
            "aiTextCheck", "crossCheck", "pricingLogic",
        ]
        for ct in check_types:
            skill_info = _CHECK_SKILL_MAP.get(ct)
            if not skill_info:
                continue
            module_path, class_name = skill_info
            try:
                import importlib
                module = importlib.import_module(module_path)
                skill_class = getattr(module, class_name)
                skill = skill_class()
                params = {"tender_text": tender_text, "bid_text": bid_text}
                if ct == "duplicate":
                    params = {"bid_text": bid_text, "reference_texts": []}
                elif ct == "aiTextCheck":
                    params = {"bid_text": bid_text}
                ctx = SkillContext(project_id="", db=db, llm=gateway, parameters=params)
                result = await skill.safe_execute(ctx)
                all_results[ct] = {
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                }
            except Exception as e:
                all_results[ct] = {"success": False, "error": str(e)}

        has_critical = any(
            r.get("data", {}).get("has_critical_issues") or r.get("data", {}).get("risk_level") == "high"
            for r in all_results.values()
            if r.get("success") and isinstance(r.get("data"), dict)
        )

        return {
            "success": True,
            "data": all_results,
            "has_critical": has_critical,
            "source": "upload",
            "bid_filename": bid_file.filename,
            "tender_filename": tender_file.filename if tender_file else None,
        }

    skill_info = _CHECK_SKILL_MAP.get(check_type)
    if not skill_info:
        if check_type == "selfcheck":
            from services.check.skills.selfcheck_list_skill import SelfcheckListSkill
            skill = SelfcheckListSkill()
            params = {"check_results": {}}
        else:
            raise HTTPException(status_code=400, detail=f"不支持的检查类型: {check_type}")
    else:
        module_path, class_name = skill_info
        import importlib
        module = importlib.import_module(module_path)
        skill_class = getattr(module, class_name)
        skill = skill_class()
        params = {"tender_text": tender_text, "bid_text": bid_text}
        if check_type == "duplicate":
            params = {"bid_text": bid_text, "reference_texts": []}
        elif check_type == "aiTextCheck":
            params = {"bid_text": bid_text}

    ctx = SkillContext(project_id="", db=db, llm=gateway, parameters=params)
    skill_result = await skill.safe_execute(ctx)

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
        "source": "upload",
        "bid_filename": bid_file.filename,
        "tender_filename": tender_file.filename if tender_file else None,
    }


@router.post("/{project_id}/signature")
async def check_signature(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.signature_check_skill import SignatureCheckSkill
    gateway = get_llm_gateway()
    skill = SignatureCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.SIGNATURE, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/validity")
async def check_validity(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.validity_check_skill import ValidityCheckSkill
    gateway = get_llm_gateway()
    skill = ValidityCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.VALIDITY, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/consistency")
async def check_consistency(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.consistency_check_skill import ConsistencyCheckSkill
    gateway = get_llm_gateway()
    skill = ConsistencyCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.CONSISTENCY, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/duplicate")
async def check_duplicate(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.duplicate_check_skill import DuplicateCheckSkill
    gateway = get_llm_gateway()
    skill = DuplicateCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"bid_text": bid_text, "reference_texts": []})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.DUPLICATE, results=skill_result.data, risk_level=skill_result.data.get("overall_risk", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/mandatory-req")
async def check_mandatory_req(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    if not tender_text or not bid_text:
        raise HTTPException(status_code=400, detail="招标文件或投标文件内容为空")
    from services.check.skills.mandatory_req_check_skill import MandatoryReqCheckSkill
    gateway = get_llm_gateway()
    skill = MandatoryReqCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.MANDATORY, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.get("/{project_id}/reports/{report_id}/export")
async def export_check_report(
    project_id: str,
    report_id: str,
    format: str = "markdown",
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import PlainTextResponse

    result = await db.execute(select(CheckReport).where(CheckReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    project_name = project.name if project else "未命名项目"

    from services.check.skills.check_report_export_skill import CheckReportExportSkill
    from services.llm_factory import get_llm_gateway

    gateway = get_llm_gateway()
    skill = CheckReportExportSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "report_data": report.results or {},
            "format": format,
            "project_name": project_name,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if not skill_result.success:
        raise HTTPException(status_code=500, detail=skill_result.error)

    content = skill_result.data.get("content", "")
    content_type = "text/markdown" if format == "markdown" else "text/html" if format == "html" else "application/json"
    return PlainTextResponse(content=content, media_type=content_type)


@router.post("/{project_id}/doc-integrity")
async def check_doc_integrity(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.doc_integrity_check_skill import DocIntegrityCheckSkill
    gateway = get_llm_gateway()
    skill = DocIntegrityCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.DOC_INTEGRITY, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/ai-text-check")
async def check_ai_text(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.ai_text_check_skill import AITextCheckSkill
    gateway = get_llm_gateway()
    skill = AITextCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.AI_TEXT, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/risk-score")
async def check_risk_score(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    reports_result = await db.execute(
        select(CheckReport).where(CheckReport.project_id == project.id)
    )
    reports = reports_result.scalars().all()
    check_results = {r.type.value if isinstance(r.type, CheckType) else str(r.type): r.results for r in reports}
    from services.check.skills.risk_score_skill import RiskScoreSkill
    skill = RiskScoreSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=get_llm_gateway(), parameters={"check_results": check_results})
    skill_result = await skill.safe_execute(ctx)
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error}


@router.post("/{project_id}/cross-check")
async def check_cross(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.cross_check_skill import CrossCheckSkill
    gateway = get_llm_gateway()
    skill = CrossCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.CROSS_CHECK, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/sample-report")
async def check_sample_report(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.sample_report_check_skill import SampleReportCheckSkill
    gateway = get_llm_gateway()
    skill = SampleReportCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.SAMPLE_REPORT, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/joint-bid")
async def check_joint_bid(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.joint_bid_check_skill import JointBidCheckSkill
    gateway = get_llm_gateway()
    skill = JointBidCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.JOINT_BID, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/ebid-submit")
async def check_ebid_submit(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.ebid_submit_check_skill import EbidSubmitCheckSkill
    gateway = get_llm_gateway()
    skill = EbidSubmitCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.EBID_SUBMIT, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


@router.post("/{project_id}/pricing-logic")
async def check_pricing_logic(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.pricing_logic_check_skill import PricingLogicCheckSkill
    gateway = get_llm_gateway()
    skill = PricingLogicCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.PRICING_LOGIC, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}
