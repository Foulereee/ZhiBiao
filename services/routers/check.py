from __future__ import annotations

import asyncio
import importlib
import logging
import re
import tempfile
import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import (
    Project, Document, Analysis, Chapter, CheckReport,
    ProjectStatus, CheckType,
)
from services.llm_factory import get_llm_gateway
from core.skill_engine.base import SkillContext
from core.task_manager import TaskManager
from core.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB


def _truncate_text(text: str, max_chars: int) -> str:
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[... 内容已截断，已省略后续部分 ...]"


async def _get_tender_and_bid_text(project_id: str, db: AsyncSession):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    max_chars = get_settings().tender_text_max_chars

    tender_text = ""
    if project.tender_doc_id:
        doc_result = await db.execute(
            select(Document).where(Document.id == project.tender_doc_id)
        )
        doc = doc_result.scalar_one_or_none()
        if doc and doc.parsed_content:
            tender_text = _truncate_text(doc.parsed_content, max_chars)

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

    bid_text = _truncate_text(bid_text, max_chars)

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

        # Extract max_price for pricing check
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

        # Extract bid_deadline for qualification check
        timeline = analysis.dimensions.get("timeline", {}) if analysis and analysis.dimensions else {}
        bid_deadline = timeline.get("投标截止日", "") if isinstance(timeline, dict) else ""

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
            parameters={"tender_text": tender_text, "bid_text": bid_text, "max_price": max_price},
        )
        pricing_result = await pricing_skill.safe_execute(pricing_ctx)
        if pricing_result.success:
            check_results["pricing_check"] = pricing_result.data

        from services.check.skills.qualification_check_skill import QualificationCheckSkill
        qual_skill = QualificationCheckSkill()
        qual_ctx = SkillContext(
            project_id=project_id, db=db, llm=gateway,
            parameters={"tender_text": tender_text, "bid_text": bid_text, "bid_deadline": bid_deadline},
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
    """Submit full check as async task. Returns task_id for polling."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    project.status = ProjectStatus.CHECKING
    await db.flush()
    await db.commit()

    tm = TaskManager.instance()
    task = await tm.submit("full_check", _do_full_check, project_id)

    return {
        "task_id": task.task_id,
        "status": "pending",
        "message": "全面检查任务已提交，请通过 GET /check/task/{task_id} 查询进度",
    }


async def _do_full_check(project_id: str):
    """Background worker: run 15 check skills in parallel and persist results."""
    from services.database import async_session

    session_factory = async_session()
    async with session_factory() as db:
        try:
            project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

            if not tender_text or not bid_text:
                raise ValueError("招标文件或投标文件内容为空")

            gateway = get_llm_gateway()

            # Extract supplementary parameters
            analysis_result = await db.execute(
                select(Analysis).where(Analysis.project_id == project.id)
            )
            analysis = analysis_result.scalar_one_or_none()
            max_price = None
            bid_deadline = ""
            if analysis and analysis.dimensions:
                project_info = analysis.dimensions.get("project_info", {})
                if isinstance(project_info, dict):
                    budget_str = project_info.get("预算金额", "")
                    if budget_str:
                        import re
                        match = re.search(r"[\d.]+", str(budget_str))
                        if match:
                            max_price = float(match.group())
                timeline = analysis.dimensions.get("timeline", {})
                if isinstance(timeline, dict):
                    bid_deadline = timeline.get("投标截止日", "")

            # Build skill tasks for parallel execution
            import importlib

            async def _run_skill(ct: str, params: dict) -> tuple[str, dict]:
                skill_info = _CHECK_SKILL_MAP.get(ct)
                if not skill_info:
                    return ct, {"success": False, "error": f"未知的检查类型: {ct}"}
                module_path, class_name = skill_info
                try:
                    module = importlib.import_module(module_path)
                    skill_class = getattr(module, class_name)
                    skill = skill_class()
                    # Each skill gets its own DB session to avoid concurrent access issues
                    async with session_factory() as skill_db:
                        ctx = SkillContext(project_id=project_id, db=skill_db, llm=gateway, parameters=params)
                        result = await skill.safe_execute(ctx)
                    return ct, {
                        "success": result.success,
                        "data": result.data,
                        "error": result.error,
                    }
                except Exception as e:
                    return ct, {"success": False, "error": str(e)}

            # Build project_facts for consistency check (same as standalone endpoint)
            project_facts = {}
            if analysis and analysis.dimensions:
                project_facts = {
                    "project_name": project.name,
                    "dimensions": analysis.dimensions,
                }

            # 15 check types with appropriate parameters
            base_params = {"tender_text": tender_text, "bid_text": bid_text}
            skill_tasks = [
                ("compliance", base_params),
                ("disqualification", base_params),
                ("qualification", {**base_params, "bid_deadline": bid_deadline}),
                ("pricing", {**base_params, "max_price": max_price}),
                ("fitScore", base_params),
                ("deposit", base_params),
                ("signature", base_params),
                ("validity", base_params),
                ("consistency", {**base_params, "project_facts": project_facts}),
                ("duplicate", {"bid_text": bid_text, "reference_texts": []}),
                ("mandatoryReq", base_params),
                ("docIntegrity", base_params),
                ("aiTextCheck", {"bid_text": bid_text}),
                ("crossCheck", base_params),
                ("pricingLogic", base_params),
            ]

            # Run all skills in parallel
            results = await asyncio.gather(
                *[_run_skill(ct, params) for ct, params in skill_tasks],
                return_exceptions=True,
            )

            all_results = {}
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"[full_check] skill 异常被 asyncio.gather 捕获: {r}")
                    continue
                ct, result_dict = r
                all_results[ct] = result_dict

            has_critical = any(
                r.get("data", {}).get("has_critical_issues") or r.get("data", {}).get("risk_level") == "high"
                for r in all_results.values()
                if r.get("success") and isinstance(r.get("data"), dict)
            )

            # Persist report
            report = CheckReport(
                project_id=project.id,
                type=CheckType.FULL_CHECK,
                results=all_results,
                risk_level="high" if has_critical else "low",
                summary={"checks_run": len(all_results), "has_critical": has_critical},
            )
            db.add(report)
            project.status = ProjectStatus.COMPLETED
            await db.flush()
            await db.commit()

            return {
                "success": True,
                "data": all_results,
                "has_critical": has_critical,
            }
        except Exception as e:
            logger.error(f"[full_check] 异常: {e}")
            try:
                project_result = await db.execute(
                    select(Project).where(Project.id == project_id)
                )
                proj = project_result.scalar_one_or_none()
                if proj:
                    proj.status = ProjectStatus.COMPLETED
                    await db.commit()
            except Exception:
                pass
            raise  # Let TaskManager correctly mark the task as FAILED


@router.get("/task/{task_id}")
async def get_check_task_status(task_id: str):
    """Poll endpoint for async check tasks."""
    tm = TaskManager.instance()
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.to_dict()


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
    if len(content_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限",
        )

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

# ---------------------------------------------------------------------------
# Async single-check: mapping, helpers, worker, endpoint
# ---------------------------------------------------------------------------

_CHECK_TYPE_TO_ENUM: dict[str, CheckType] = {
    "compliance": CheckType.COMPLIANCE,
    "disqualification": CheckType.DISQUALIFICATION,
    "qualification": CheckType.QUALIFICATION,
    "pricing": CheckType.PRICING,
    "fitScore": CheckType.FIT_SCORE,
    "deposit": CheckType.DEPOSIT,
    "signature": CheckType.SIGNATURE,
    "validity": CheckType.VALIDITY,
    "consistency": CheckType.CONSISTENCY,
    "duplicate": CheckType.DUPLICATE,
    "mandatoryReq": CheckType.MANDATORY,
    "docIntegrity": CheckType.DOC_INTEGRITY,
    "aiTextCheck": CheckType.AI_TEXT,
    "riskScore": CheckType.RISK_SCORE,
    "crossCheck": CheckType.CROSS_CHECK,
    "sampleReport": CheckType.SAMPLE_REPORT,
    "jointBid": CheckType.JOINT_BID,
    "ebidSubmit": CheckType.EBID_SUBMIT,
    "pricingLogic": CheckType.PRICING_LOGIC,
    "selfcheck": CheckType.SELFCHECK,
}


class SingleCheckRequest(BaseModel):
    check_type: str


async def _build_check_params(
    check_type: str,
    project_id: str,
    db: AsyncSession,
    project: Project,
    tender_text: str,
    bid_text: str,
) -> dict:
    """Build skill-specific parameters based on check_type."""
    base = {"tender_text": tender_text, "bid_text": bid_text}

    if check_type in ("compliance", "fitScore", "deposit", "signature",
                      "validity", "mandatoryReq", "docIntegrity",
                      "crossCheck", "sampleReport", "jointBid",
                      "ebidSubmit", "pricingLogic", "disqualification"):
        # disqualification needs extra clauses
        if check_type == "disqualification":
            analysis_result = await db.execute(
                select(Analysis).where(Analysis.project_id == project.id)
            )
            analysis = analysis_result.scalar_one_or_none()
            dq_clauses: list = []
            if analysis and analysis.dimensions:
                dq_data = analysis.dimensions.get("disqualification", {})
                if dq_data and not dq_data.get("error"):
                    dq_clauses = dq_data.get("clauses", [])
            return {**base, "disqualification_clauses": dq_clauses}
        return base

    if check_type == "qualification":
        analysis_result = await db.execute(
            select(Analysis).where(Analysis.project_id == project.id)
        )
        analysis = analysis_result.scalar_one_or_none()
        timeline = analysis.dimensions.get("timeline", {}) if analysis and analysis.dimensions else {}
        bid_deadline = timeline.get("投标截止日", "") if isinstance(timeline, dict) else ""
        return {**base, "bid_deadline": bid_deadline}

    if check_type == "pricing":
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
                    match = re.search(r"[\d.]+", str(budget_str))
                    if match:
                        max_price = float(match.group())
        return {**base, "max_price": max_price}

    if check_type == "consistency":
        analysis_result = await db.execute(
            select(Analysis).where(Analysis.project_id == project.id)
        )
        analysis = analysis_result.scalar_one_or_none()
        project_facts: dict = {}
        if analysis and analysis.dimensions:
            project_facts = {"project_name": project.name, "dimensions": analysis.dimensions}
        return {**base, "project_facts": project_facts}

    if check_type == "duplicate":
        reference_texts: list[str] = []
        try:
            other_docs_result = await db.execute(
                select(Document).where(
                    Document.project_id != project.id,
                    Document.type == "bid",
                    Document.parsed_content.isnot(None),
                ).limit(10)
            )
            other_docs = other_docs_result.scalars().all()
            reference_texts = [doc.parsed_content for doc in other_docs if doc.parsed_content]
        except Exception:
            pass
        return {"bid_text": bid_text, "reference_texts": reference_texts}

    if check_type == "aiTextCheck":
        return {"bid_text": bid_text}

    if check_type == "riskScore":
        reports_result = await db.execute(
            select(CheckReport).where(CheckReport.project_id == project.id)
        )
        reports = reports_result.scalars().all()
        check_results = {
            r.type.value if isinstance(r.type, CheckType) else str(r.type): r.results
            for r in reports
        }
        return {"check_results": check_results}

    # fallback
    return base


async def _do_single_check(project_id: str, check_type: str):
    """Background worker: run a single check (or selfcheck) and persist results."""
    from services.database import async_session

    session_factory = async_session()
    async with session_factory() as db:
        project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

        if not tender_text or not bid_text:
            raise ValueError("招标文件或投标文件内容为空")

        gateway = get_llm_gateway()

        # --- selfcheck: 3 sub-skills in parallel + summary skill ---
        if check_type == "selfcheck":
            analysis_result = await db.execute(
                select(Analysis).where(Analysis.project_id == project.id)
            )
            analysis = analysis_result.scalar_one_or_none()
            max_price = None
            bid_deadline = ""
            if analysis and analysis.dimensions:
                pi = analysis.dimensions.get("project_info", {})
                if isinstance(pi, dict):
                    budget_str = pi.get("预算金额", "")
                    if budget_str:
                        m = re.search(r"[\d.]+", str(budget_str))
                        if m:
                            max_price = float(m.group())
                timeline = analysis.dimensions.get("timeline", {})
                if isinstance(timeline, dict):
                    bid_deadline = timeline.get("投标截止日", "")

            check_results: dict = {}

            async def _run_sub(skill_cls, params: dict, key: str):
                skill = skill_cls()
                async with session_factory() as sub_db:
                    ctx = SkillContext(project_id=project_id, db=sub_db, llm=gateway, parameters=params)
                    res = await skill.safe_execute(ctx)
                return key, res

            from services.check.skills.compliance_check_skill import ComplianceCheckSkill
            from services.check.skills.pricing_check_skill import PricingCheckSkill
            from services.check.skills.qualification_check_skill import QualificationCheckSkill

            sub_tasks = [
                _run_sub(ComplianceCheckSkill, {"tender_text": tender_text, "bid_text": bid_text}, "compliance_check"),
                _run_sub(PricingCheckSkill, {"tender_text": tender_text, "bid_text": bid_text, "max_price": max_price}, "pricing_check"),
                _run_sub(QualificationCheckSkill, {"tender_text": tender_text, "bid_text": bid_text, "bid_deadline": bid_deadline}, "qualification_check"),
            ]
            sub_results = await asyncio.gather(*sub_tasks, return_exceptions=True)
            for sr in sub_results:
                if isinstance(sr, Exception):
                    logger.warning(f"[selfcheck] sub-skill error: {sr}")
                    continue
                key, res = sr
                if res.success:
                    check_results[key] = res.data

            from services.check.skills.selfcheck_list_skill import SelfcheckListSkill
            skill = SelfcheckListSkill()
            async with session_factory() as skill_db:
                ctx = SkillContext(
                    project_id=project_id, db=skill_db, llm=gateway,
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
                await db.commit()

            return {
                "success": skill_result.success,
                "data": skill_result.data,
                "error": skill_result.error,
                "warnings": skill_result.warnings,
            }

        # --- normal single check ---
        params = await _build_check_params(check_type, project_id, db, project, tender_text, bid_text)
        skill_info = _CHECK_SKILL_MAP.get(check_type)
        if not skill_info:
            raise ValueError(f"未知的检查类型: {check_type}")

        module_path, class_name = skill_info
        module = importlib.import_module(module_path)
        skill_class = getattr(module, class_name)
        skill = skill_class()

        async with session_factory() as skill_db:
            ctx = SkillContext(project_id=project_id, db=skill_db, llm=gateway, parameters=params)
            skill_result = await skill.safe_execute(ctx)

        if skill_result.success:
            check_enum = _CHECK_TYPE_TO_ENUM.get(check_type)
            if check_enum:
                risk_level = "low"
                if isinstance(skill_result.data, dict):
                    risk_level = (
                        skill_result.data.get("risk_level")
                        or skill_result.data.get("overall_risk")
                        or "low"
                    )
                report = CheckReport(
                    project_id=project.id,
                    type=check_enum,
                    results=skill_result.data,
                    risk_level=risk_level,
                )
                db.add(report)
                await db.flush()
                await db.commit()

        return {
            "success": skill_result.success,
            "data": skill_result.data,
            "error": skill_result.error,
            "warnings": skill_result.warnings,
        }


@router.post("/{project_id}/check-async")
async def submit_single_check(
    project_id: str,
    body: SingleCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit any single check as an async task. Returns task_id for polling."""
    check_type = body.check_type

    # Validate project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # Validate check_type
    valid_types = set(_CHECK_TYPE_TO_ENUM.keys())
    if check_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的检查类型: {check_type}。支持: {', '.join(sorted(valid_types))}",
        )

    tm = TaskManager.instance()
    task = await tm.submit("single_check", _do_single_check, project_id, check_type)

    return {
        "task_id": task.task_id,
        "status": "pending",
        "message": f"{check_type} 检查任务已提交",
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
        all_results: dict = {}
        check_types = [
            "compliance", "disqualification", "qualification", "pricing",
            "fitScore", "deposit", "signature", "validity",
            "consistency", "duplicate", "mandatoryReq", "docIntegrity",
            "aiTextCheck", "crossCheck", "pricingLogic",
        ]

        async def _run_upload_skill(ct: str) -> tuple[str, dict]:
            skill_info = _CHECK_SKILL_MAP.get(ct)
            if not skill_info:
                return ct, {"success": False, "error": f"未知检查类型: {ct}"}
            module_path, class_name = skill_info
            try:
                module = importlib.import_module(module_path)
                skill_class = getattr(module, class_name)
                skill = skill_class()
                params: dict = {"tender_text": tender_text, "bid_text": bid_text}
                if ct == "duplicate":
                    params = {"bid_text": bid_text, "reference_texts": []}
                elif ct == "aiTextCheck":
                    params = {"bid_text": bid_text}
                # Each skill gets its own session to avoid concurrent access
                from services.database import async_session
                session_factory = async_session()
                async with session_factory() as skill_db:
                    ctx = SkillContext(project_id="", db=skill_db, llm=gateway, parameters=params)
                    result = await skill.safe_execute(ctx)
                return ct, {
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                }
            except Exception as e:
                return ct, {"success": False, "error": str(e)}

        gather_results = await asyncio.gather(
            *[_run_upload_skill(ct) for ct in check_types],
            return_exceptions=True,
        )
        for r in gather_results:
            if isinstance(r, Exception):
                logger.warning(f"[upload-check] skill exception: {r}")
                continue
            ct, result_dict = r
            all_results[ct] = result_dict

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

    # Build project_facts from analysis data for rule-based consistency checks
    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    project_facts = {}
    if analysis and analysis.dimensions:
        project_facts = {
            "project_name": project.name,
            "dimensions": analysis.dimensions,
        }

    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text, "project_facts": project_facts})
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

    # Build reference_texts from other projects' bid documents for cross-project dedup
    reference_texts = []
    try:
        other_docs_result = await db.execute(
            select(Document).where(
                Document.project_id != project.id,
                Document.type == "bid",
                Document.parsed_content.isnot(None),
            ).limit(10)
        )
        other_docs = other_docs_result.scalars().all()
        reference_texts = [doc.parsed_content for doc in other_docs if doc.parsed_content]
    except Exception:
        pass

    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"bid_text": bid_text, "reference_texts": reference_texts})
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


@router.get("/{project_id}/reports/{report_id}/content")
async def get_check_report_content(
    project_id: str,
    report_id: str,
    format: str = "markdown",
    db: AsyncSession = Depends(get_db),
):
    """直接返回报告内容(用于前端预览)，不触发下载。"""
    from services.check.skills.check_report_export_skill import CheckReportExportSkill
    from services.llm_factory import get_llm_gateway

    result = await db.execute(select(CheckReport).where(CheckReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    project_name = project.name if project else "未命名项目"

    if not report.results:
        return {
            "success": True,
            "report_id": report_id,
            "format": format,
            "content": "",
            "project_name": project_name,
            "size": 0,
        }

    gateway = get_llm_gateway()
    skill = CheckReportExportSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "report_data": report.results,
            "format": format,
            "project_name": project_name,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if not skill_result.success:
        raise HTTPException(status_code=500, detail=skill_result.error or "报告生成失败")

    return {
        "success": True,
        "report_id": report_id,
        "format": format,
        "content": skill_result.data.get("content", ""),
        "size": skill_result.data.get("size", 0),
        "project_name": project_name,
        "generated_at": skill_result.data.get("generated_at"),
    }


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
    if skill_result.success:
        report = CheckReport(
            project_id=project.id,
            type=CheckType.RISK_SCORE,
            results=skill_result.data,
            risk_level=skill_result.data.get("risk_level", "low"),
            summary={"score": skill_result.data.get("score", 0)},
        )
        db.add(report)
        await db.flush()
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
