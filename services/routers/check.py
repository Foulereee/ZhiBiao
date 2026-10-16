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
    iso_utc, iso_local, local_str, iso_now_local,
)
from services.llm_factory import get_llm_gateway
from core.skill_engine.base import SkillContext
from core.task_manager import TaskManager
from core.settings import get_settings
from services.llm_factory import get_llm_gateway as _get_llm_gateway_raw


class _ModelPinnedLLM:
    """把"检查类"技能的模型固定到检查专用快速模型(BMP_LLM_CHECK_MODEL)。

    背景:平台默认模型是推理型的 sensenova-6.8-flash-lite,同一份合规性检查 prompt
    实测单次调用 749.8s(思考把 8192/16384 预算吃满后还要提额重试),客户反馈
    "执行检查中时间特别长";换 glm-5.2 实测 48.1s / 78.1s,deepseek-v4-flash 49.7s。
    检查是"结构化逐条比对",不依赖长链推理,所以检查专用快模型;生成/写作仍走
    平台默认模型。未配置 BMP_LLM_CHECK_MODEL 时行为与改动前完全一致。
    """

    def __init__(self, inner, model: str | None = None):
        self._inner = inner
        self._model = (model or "").strip() or None

    async def collect_json(self, *args, **kwargs):
        if self._model:
            kwargs.setdefault("model", self._model)
        kwargs.setdefault("request_timeout", _check_timeout())
        return await self._inner.collect_json(*args, **kwargs)

    async def chat(self, *args, **kwargs):
        if self._model:
            kwargs.setdefault("model", self._model)
        kwargs.setdefault("request_timeout", _check_timeout())
        return await self._inner.chat(*args, **kwargs)

    def __getattr__(self, name):
        # 其余能力(stream_chat 等)原样透传
        return getattr(self._inner, name)

    @property
    def default_model(self) -> str:
        """对外报告"实际使用的模型"。

        没有这个属性时,包装类会把内层网关的 default_model(平台默认模型)透传出去,
        修复方案页面上就会显示"sensenova-6.8-flash-lite",而实际调用的是检查专用模型。
        """
        return self._model or str(getattr(self._inner, "default_model", "") or "")


def _check_timeout() -> float:
    """检查类技能的单次调用超时(秒)。

    检查模型实测 30-114s,给 150s 留余量;比客户端默认 300s 短,避免
    "一次调用挂住 5 分钟再重试"把单项检查拖成十几分钟。
    """
    try:
        return float(os.environ.get("BMP_LLM_CHECK_TIMEOUT", "150") or 150)
    except (TypeError, ValueError):
        return 150.0


def _check_llm():
    """检查类技能使用的 LLM;配置了 BMP_LLM_CHECK_MODEL 时固定到检查专用模型。"""
    gateway = _get_llm_gateway_raw()
    model = (os.environ.get("BMP_LLM_CHECK_MODEL") or "").strip()
    if not model:
        return gateway
    return _ModelPinnedLLM(gateway, model)


logger = logging.getLogger(__name__)
from services.middleware.api_key import require_any_auth

router = APIRouter(dependencies=[Depends(require_any_auth)])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 上传文件分块读取大小(1MB)，边读边校验大小


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

    gateway = _check_llm()
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
            # tender_interpret_skill 声明的字段是 disqualification_clauses，
            # 这里原来只读 "clauses" —— 线上两个项目实测都取不到，
            # 于是一次次退回"现场让模型重新提取废标条款"（慢且可能漏）。
            dq_clauses = (
                dq_data.get("disqualification_clauses")
                or dq_data.get("clauses")
                or []
            )
            # 兼容字符串形态：解读结果里 substantive_requirements /
            # mandatory_conditions 是整段文字而非条目数组。
            if not dq_clauses:
                for key in ("substantive_requirements", "mandatory_conditions"):
                    val = dq_data.get(key)
                    if isinstance(val, str) and val.strip():
                        dq_clauses.append({
                            "id": f"AUTO-{key}",
                            "type": "invalidBid",
                            "content": val.strip(),
                            "severity": "critical",
                        })

    from services.check.skills.disqualification_check_skill import DisqualificationCheckSkill

    gateway = _check_llm()
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

    gateway = _check_llm()
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

    gateway = _check_llm()
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

    gateway = _check_llm()
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
        gateway = _check_llm()

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
        llm=_check_llm(),
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
    """Background worker: run the full check set (up to 19 skills) in parallel and persist results."""
    from services.database import async_session

    session_factory = async_session()
    async with session_factory() as db:
        try:
            project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)

            if not tender_text or not bid_text:
                raise ValueError("招标文件或投标文件内容为空")

            gateway = _check_llm()

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
            # 这里不要再写 "import importlib"：函数内 import 会让 importlib 成为本函数
            # 的局部名，使下面嵌套协程里的引用变成未绑定的 free variable（同类陷阱，
            # 上传检查分支就是这么坏的）。模块顶部已有全局 import。
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

            # 全面检查覆盖 19 项(原先只有 15 项,导致"全面检查"结果数与侧边栏 21 个单项对不上):
            # 补入 jointBid / ebidSubmit / scoreCoverage;riskScore 依赖其它检查结果,放到最后单独执行。
            # 仍然不进全面检查的只有 selfcheck(自带 3 个子技能+汇总,单独跑)与 sampleReport(演示用)。
            base_params = {"tender_text": tender_text, "bid_text": bid_text}

            # duplicate:与单项检查同一口径,用其它项目的投标文件做查重参照(原来传的是空列表)
            reference_texts: list[str] = []
            try:
                other_docs_result = await db.execute(
                    select(Document)
                    .where(
                        Document.project_id != project.id,
                        Document.type == "bid",
                        Document.parsed_content.isnot(None),
                    )
                    .limit(10)
                )
                reference_texts = [
                    d.parsed_content for d in other_docs_result.scalars().all() if d.parsed_content
                ]
            except Exception:
                pass

            # scoreCoverage 需要评分矩阵与大纲章节
            matrix = (
                analysis.scoring_matrix
                if analysis and isinstance(analysis.scoring_matrix, dict)
                else {}
            )
            matrix_rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
            outline_sections: list = []
            try:
                from services.models import Outline as _OutlineModel

                outline_result = await db.execute(
                    select(_OutlineModel).where(_OutlineModel.project_id == project.id)
                )
                outline_obj = outline_result.scalar_one_or_none()
                if outline_obj and isinstance(outline_obj.tree, list):
                    outline_sections = outline_obj.tree
            except Exception:
                pass

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
                ("duplicate", {"bid_text": bid_text, "reference_texts": reference_texts}),
                ("mandatoryReq", base_params),
                ("docIntegrity", base_params),
                ("aiTextCheck", {"bid_text": bid_text}),
                ("crossCheck", base_params),
                ("jointBid", base_params),
                ("ebidSubmit", base_params),
                ("pricingLogic", base_params),
            ]
            if matrix_rows:
                skill_tasks.append(
                    ("scoreCoverage", {"scoring_matrix": matrix, "outline_sections": outline_sections})
                )

            # 全量检查项也不能无上限并发：17~18 个 skill 一起打 LLM 会瞬间打满上游配额，
            # 这里同样限制最多 4 个并发(结果顺序与 skill_tasks 一致，日志统计不变)
            _full_check_semaphore = asyncio.Semaphore(4)

            async def _run_skill_limited(ct: str, params: dict) -> tuple[str, dict]:
                async with _full_check_semaphore:
                    return await _run_skill(ct, params)

            # Run all skills in parallel
            results = await asyncio.gather(
                *[_run_skill_limited(ct, params) for ct, params in skill_tasks],
                return_exceptions=True,
            )

            all_results = {}
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"[full_check] skill 异常被 asyncio.gather 捕获: {r}")
                    continue
                ct, result_dict = r
                all_results[ct] = result_dict

            # riskScore 要汇总其它检查的结果,单项检查里也是这个口径,因此放在并行之后
            try:
                risk_ct, risk_result = await _run_skill("riskScore", {"check_results": all_results})
                all_results[risk_ct] = risk_result
            except Exception as e:
                logger.warning(f"[full_check] riskScore 执行失败: {e}")

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


# ---------------------------------------------------------------------------
# 检查问题修复:用户在检查结果里点「一键生成修复方案」
# ---------------------------------------------------------------------------
_FIX_PLAN_KEY = "__fix_plan__"


def _collect_problems(checks: list) -> list:
    """挑出需要修复的条目(status 为 fail/warning),带 idx 便于前端与大模型对齐。"""
    out: list[dict] = []
    for idx, c in enumerate(checks or []):
        if not isinstance(c, dict):
            continue
        st = str(c.get("status") or "").lower()
        if st in ("fail", "failed", "error", "warning", "warn", "risk"):
            out.append({
                "idx": idx,
                "check_name": str(c.get("check_name") or ""),
                "status": st,
                "detail": str(c.get("detail") or "")[:400],
                "suggestion": str(c.get("suggestion") or "")[:400],
                "required": str(c.get("required") or "")[:200],
                "actual": str(c.get("actual") or "")[:200],
                # 汇总行(如"合规性检查（汇总）")是整份文件多条内容的统计行,不对应某一个段落,
                # 拿它去正文里定位会命中一大段无关文字(实测匹配到 1108 字),
                # 整段替换就会把那一大段删掉。所以这里带上标记,后续禁止对它做整段替换。
                "is_summary": bool(c.get("is_summary")),
            })
    return out


def _parse_fix_plan(payload: object, problems: list) -> list:
    """规范化大模型返回的修复方案:容忍外层包一层、字段换名、条数不齐。"""
    if isinstance(payload, dict):
        for key in ("fixes", "fix_plan", "items", "plans", "results", "solutions", "repairs", "list"):
            v = payload.get(key)
            if isinstance(v, list) and v:
                payload = v
                break
        else:
            inner = payload.get("data")
            if isinstance(inner, (dict, list)):
                return _parse_fix_plan(inner, problems)
            payload = [payload]
    if not isinstance(payload, list):
        return []

    by_idx = {p["idx"]: p for p in problems}
    out: list[dict] = []
    for i, item in enumerate(payload):
        if isinstance(item, str):
            item = {"fix_text": item}
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("idx", item.get("index", i)))
        except Exception:
            idx = i
        base = by_idx.get(idx, {})
        steps = item.get("steps") or item.get("actions") or item.get("how") or []
        if isinstance(steps, str):
            steps = [s.strip() for s in re.split(r"[\n;；]", steps) if s.strip()]
        fix_text = (
            item.get("fix_text") or item.get("fixed_text") or item.get("replacement")
            or item.get("suggested_text") or item.get("content") or item.get("fix") or ""
        )
        out.append({
            "idx": idx,
            "check_name": str(item.get("check_name") or base.get("check_name") or ""),
            "problem": str(item.get("problem") or item.get("issue") or base.get("detail") or "")[:400],
            "where": str(item.get("where") or item.get("location") or item.get("clause") or "")[:300],
            "why": str(item.get("why") or item.get("reason") or item.get("cause") or "")[:400],
            "fix_text": str(fix_text)[:4000],
            "steps": [str(s)[:300] for s in steps][:8] if isinstance(steps, list) else [],
            "manual": str(item.get("manual") or item.get("manual_path") or "")[:400],
            "severity": str(item.get("severity") or item.get("risk_level") or base.get("status") or "")[:20],
        })
    return out


async def _do_fix_plan(project_id: str, report_id: str):
    """后台:对一份检查报告里的问题项生成逐条修复方案,并回写到报告里。"""
    from datetime import datetime as _dt

    from services.database import async_session

    session_factory = async_session()
    async with session_factory() as db:
        _project, tender_text, _bid_text = await _get_tender_and_bid_text(project_id, db)
        rep = (
            await db.execute(select(CheckReport).where(CheckReport.id == report_id))
        ).scalar_one_or_none()
        if rep is None:
            raise ValueError("检查报告不存在")

        normalized = _report_to_checks(rep.results, rep.risk_level, rep.type)
        problems = _collect_problems(normalized.get("checks") or [])
        if not problems:
            plan = {
                "generated_at": iso_now_local(),
                "model": "", "problem_count": 0,
                "summary": "本次检查未发现需要修复的问题项,无需整改。",
                "fixes": [],
            }
            res = dict(rep.results or {})
            res[_FIX_PLAN_KEY] = plan
            rep.results = res
            await db.commit()
            return {"report_id": report_id, "problem_count": 0}

        gateway = _check_llm()
        # 关键:先把每条问题在标书正文里定位到的"当前原文段落"取出来(纯本地检索,不额外调模型),
        # 随问题清单一并交给模型。原来的提示词只给了检查项/问题/建议,还限死"200字内",
        # 模型看不到原文,只能回一句短摘要;而替换是按整段(200~400字)命中的,
        # 结果整段替换会连原文里的有效信息一起删掉。
        located: dict[int, str] = {}
        _summary_by_idx = {p["idx"]: bool(p.get("is_summary")) for p in problems[:25]}
        for p in problems[:25]:
            if p.get("is_summary"):
                located[p["idx"]] = ""
                continue
            try:
                _loc = await _locate_in_project(
                    _project,
                    " ".join(str(p.get(k) or "") for k in ("check_name", "detail", "suggestion")),
                    "",
                    db,
                )
            except Exception as e:  # 定位失败不影响方案生成
                logger.warning(f"[fix_plan] 第 {p['idx']} 条原文定位失败: {e}")
                _loc = {}
            located[p["idx"]] = str(_loc.get("matched") or "").strip()[:600]

        tender_excerpt = (tender_text or "")[:5000]
        _schema = (
            "\n\n请为下面清单里的每一条问题输出修复方案,严格按此 JSON 结构返回:"
            '{"summary":"整体整改思路(100字内)","fixes":[{"idx":0,"check_name":"检查项名",'
            '"problem":"问题简述","where":"问题在投标文件中的位置(章节/条款)","why":"为什么不合规",'
            '"fix_text":"可整段替换上面原文段落的完整文本","steps":["操作步骤1","操作步骤2"],'
            '"manual":"若不改标书时的手动处理路径"}]}'
            "\n\nfix_text 的硬性要求(直接决定能不能自动替换,务必遵守):"
            "\n1) 必须是完整段落,写成可以直接粘进标书的正式表述,不是提纲、不是摘要、不是一句话结论;"
            "\n2) 必须完整保留原文段落里所有仍然正确有效的具体信息——公司名称、金额、日期、期限、"
            "承诺事项、条款号、清单各项、必要的证明材料名称等,只修正被指出的问题,不得顺手删减;"
            "\n3) 字数控制在原文段落的 1~2 倍之间(原文标注了字数:若原文 200 字,就写 200~400 字),"
            "原文缺什么就在同一段里补足什么,需要新增的材料、承诺、证明材料清单一律写成同一段的一部分;"
            "不要无限扩写、不要堆砌套话;"
            "\n4) 如果这条问题只是「需要线下补材料、投标文件本身不用改」,也要给出加长后的完整段落,"
            "把承诺写实、写具体,不要输出空话;"
            "\n5) 不要输出「同上」「参见前文」之类的省略写法。"
            "\nidx 必须与问题清单方括号里的编号一致,不要遗漏任何一条。"
        )
        _system = {
            "role": "system",
            "content": (
                "你是资深投标文件整改专家,逐条给出可直接落地的修复方案。"
                "直接输出 JSON,不要输出任何思考过程、推理、解释或 Markdown 代码块围栏。"
            ),
        }

        def _instruction(batch: list) -> str:
            return (
                "以下是投标文件的检查问题清单,每条都附上了它在标书里的当前原文段落:\n"
                + "\n".join(
                    f"[{p['idx']}] 检查项:{p['check_name']} | 问题:{p['detail']} | 系统建议:{p['suggestion']}"
                    + (
                        f"\n     标书当前原文段落({len(located[p['idx']])}字,替换时会被整段换掉):{located[p['idx']]}"
                        if located.get(p["idx"])
                        else "\n     标书当前原文段落:(未定位到,建议追加补充说明)"
                    )
                    for p in batch
                )
                + "\n\n招标文件摘录(用于核对要求):\n" + tender_excerpt
                + _schema
            )

        # 分批并行:整改文本现在要求是"整段完整重写",输出比原来长得多。
        # 实测每批 4 条时单批输出 13590 字符、completion_tokens 撞满 8192 被截断,
        # 模型就会写出空文本或十几字的残句,所以默认每批 3 条(单批约 3~4k token,安全),
        # 并发发出,总耗时依然可控;个别仍然过短的条目再由下面的"逐条重试"补齐。
        try:
            _batch_size = max(2, min(4, int(os.environ.get("BMP_FIX_PLAN_BATCH", "3"))))
        except Exception:
            _batch_size = 3
        _problems = problems[:25]
        _batches = [
            _problems[i:i + _batch_size] for i in range(0, len(_problems), _batch_size)
        ]

        async def _gen_batch(batch: list):
            msgs = [_system, {"role": "user", "content": _instruction(batch)}]
            try:
                return await gateway.collect_json(messages=msgs, temperature=0.2)
            except Exception as e:
                logger.warning(f"[fix_plan] 一批生成失败({len(batch)}条),缩短输入重试: {e}")
                return await gateway.collect_json(
                    messages=[_system, {"role": "user", "content": _instruction(batch)[:4000]}],
                    temperature=0.2,
                )

        payloads = await asyncio.gather(
            *[_gen_batch(b) for b in _batches], return_exceptions=True
        )

        fixes: list[dict] = []
        summary = ""
        seen_idx: set = set()
        for pl in payloads:
            if isinstance(pl, BaseException):
                logger.warning(f"[fix_plan] 一批生成异常,该批问题将没有整改文本: {pl}")
                continue
            if isinstance(pl, dict) and not summary:
                summary = str(pl.get("summary") or pl.get("overall") or "")[:500]
            for f in _parse_fix_plan(pl, problems):
                if f["idx"] in seen_idx:
                    continue
                seen_idx.add(f["idx"])
                fixes.append(f)
        if not fixes:
            raise ValueError("修复方案生成失败:模型没有返回可用的整改文本,请稍后重试")
        fixes.sort(key=lambda f: f["idx"])

        # 逐条自检 + 单条重试。
        # 一批里要 4 条"整段重写"时,输出很容易撞上 8192 token 上限被截断,
        # 被截断的那批会返回空文本或只有十几个字的残句(实测出现过 11 字、0 字)。
        # 所以这里对"没有文本 / 明显短于原文"的条目单独再要一次——单条输出很小,不会再被截断。
        _by_idx = {f["idx"]: f for f in fixes}
        # 关键:先把所有问题项都登记进来。某一批整批失败时,它那几条不在 fixes 里,
        # 直接 _by_idx[p["idx"]] 会抛 KeyError(实测把整个任务打成了 failed)。
        for p in _problems:
            if p["idx"] not in _by_idx:
                _by_idx[p["idx"]] = {
                    "idx": p["idx"],
                    "check_name": p["check_name"],
                    "problem": p.get("detail") or "",
                    "where": "",
                    "why": "",
                    "fix_text": "",
                    "steps": [],
                    "manual": "",
                    "severity": p.get("status") or "",
                }

        def _too_thin(f: dict) -> bool:
            txt = str(f.get("fix_text") or "")
            floor = max(80, int(len(located.get(f["idx"], "")) * 0.5))
            return len(txt) < floor

        _thin = [p for p in _problems if _too_thin(_by_idx[p["idx"]])] if _by_idx else []
        if _thin:
            logger.info(
                f"[fix_plan] {len(_thin)} 条整改文本为空或过短,逐条重试: "
                f"{[p['idx'] for p in _thin]}"
            )
            _retry = await asyncio.gather(
                *[_gen_batch([p]) for p in _thin], return_exceptions=True
            )
            for p, got in zip(_thin, _retry):
                if isinstance(got, BaseException):
                    logger.warning(f"[fix_plan] 第 {p['idx']} 条重试失败: {got}")
                    continue
                cand = _parse_fix_plan(got, problems)
                cand = next((c for c in cand if c["idx"] == p["idx"]), None)
                if cand and len(str(cand.get("fix_text") or "")) > len(
                    str(_by_idx[p["idx"]].get("fix_text") or "")
                ):
                    _by_idx[p["idx"]] = cand
            fixes = list(_by_idx.values())
            fixes.sort(key=lambda f: f["idx"])

        # 记下"命中原文有多长、模型给的新文本有多长",前端据此提示
        # "这条新文本比原文短很多,整段替换会删内容,建议改成追加"。
        for f in fixes:
            f["orig_text"] = located.get(f["idx"], "")[:800]
            f["orig_len"] = len(located.get(f["idx"], ""))
            f["fix_len"] = len(str(f.get("fix_text") or ""))
            f["needs_manual"] = not str(f.get("fix_text") or "").strip()
            f["is_summary"] = bool(_summary_by_idx.get(f["idx"]))
        # 有的问题项没有落在任何一批里(超过 25 条),或模型漏答:这里补齐条数,避免前端少了行
        for p in _problems:
            if p["idx"] not in {f["idx"] for f in fixes}:
                fixes.append({
                    "idx": p["idx"],
                    "check_name": p["check_name"],
                    "problem": p.get("detail") or "",
                    "where": "",
                    "why": "",
                    "fix_text": "",
                    "steps": [],
                    "manual": "",
                    "severity": p.get("status") or "",
                    "orig_text": located.get(p["idx"], "")[:800],
                    "orig_len": len(located.get(p["idx"], "")),
                    "fix_len": 0,
                    "needs_manual": True,
                })
        fixes.sort(key=lambda f: f["idx"])
        plan = {
            "generated_at": iso_now_local(),
            "model": str(getattr(gateway, "default_model", "") or ""),
            "problem_count": len(problems),
            "summary": summary,
            "fixes": fixes,
        }
        res = dict(rep.results or {})
        res[_FIX_PLAN_KEY] = plan
        rep.results = res
        await db.commit()
        return {"report_id": report_id, "problem_count": len(problems), "fix_count": len(fixes)}


@router.post("/{project_id}/fix-plan")
async def create_fix_plan(project_id: str, report_id: str, db: AsyncSession = Depends(get_db)):
    """针对一份检查报告,提交「生成逐条修复方案」的异步任务。"""
    result = await db.execute(
        select(CheckReport).where(
            CheckReport.id == report_id, CheckReport.project_id == project_id
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="检查报告不存在")

    tm = TaskManager.instance()
    task = await tm.submit("fix_plan", _do_fix_plan, project_id, report_id)
    return {
        "task_id": task.task_id,
        "status": "pending",
        "message": "修复方案生成任务已提交,请通过 GET /check/task/{task_id} 查询进度",
    }


@router.get("/{project_id}/reports/{report_id}/fix-plan")
async def get_fix_plan(project_id: str, report_id: str, db: AsyncSession = Depends(get_db)):
    """读取已生成的修复方案(未生成时 has_plan=false)。"""
    report = (
        await db.execute(select(CheckReport).where(CheckReport.id == report_id))
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    plan = (report.results or {}).get(_FIX_PLAN_KEY) if isinstance(report.results, dict) else None
    return {"success": True, "report_id": report_id, "has_plan": bool(plan), "fix_plan": plan}


# ---------------------------------------------------------------------------
# 修复方案的落地:定位标书正文位置 / 一键替换为整改文本
# ---------------------------------------------------------------------------
_FIX_APPLIED_KEY = "__fix_applied__"


def _bigrams(s: str) -> set:
    t = re.sub(r"\s+", "", s or "")
    if len(t) > 1:
        return {t[i:i + 2] for i in range(len(t) - 1)}
    return {t} if t else set()


def _where_tokens(s: str) -> list:
    return [t for t in re.split(r"[^\w\u4e00-\u9fff]+", s or "") if len(t) >= 2]


def _paragraph_spans(text: str) -> list:
    return [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S[^\n]*", text or "")]


def _fix_excerpt(content: str, start: object, end: object, pad: int = 320) -> dict:
    """截取命中位置前后的上下文,供前端高亮显示。"""
    c = content or ""
    if not isinstance(start, int) or start < 0 or start > len(c):
        return {"before": c[:pad], "match": "", "after": "", "start": 0, "total": len(c)}
    e = end if isinstance(end, int) and end > start else start
    s0 = max(0, start - pad)
    e1 = min(len(c), e + pad)
    return {
        "before": c[s0:start], "match": c[start:e] or c[start:start + 200],
        "after": c[e:e1], "start": start, "total": len(c),
    }


async def _locate_in_project(project, query: str, where: str, db: AsyncSession) -> dict:
    """按一段查询文本在标书正文里找最匹配的段落(纯本地检索,不调模型)。

    生成修复方案时也要用它:必须先拿到"标书当前原文段落",才能让模型做整段重写;
    否则模型只看到问题描述,只能回一句短摘要,与命中整段的粒度不匹配。
    """
    qb = _bigrams(query)
    where_tokens = _where_tokens(where)

    candidates: list[tuple[str, str, str, str, float]] = []
    chapters = (
        await db.execute(select(Chapter).where(Chapter.project_id == project.id))
    ).scalars().all()
    for ch in chapters:
        if not (ch.content or "").strip():
            continue
        title = ch.title or "未命名章节"
        hit = 1.0 if any(t and t in title for t in where_tokens) else 0.0
        candidates.append(("chapter", ch.id, title, ch.content or "", hit))

    bid_doc = (
        await db.execute(
            select(Document).where(
                Document.project_id == project.id, Document.type == "bid"
            )
        )
    ).scalars().first()
    if bid_doc and (bid_doc.parsed_content or "").strip():
        candidates.append(
            ("document", bid_doc.id, bid_doc.original_name or "投标文件", bid_doc.parsed_content or "", 0.0)
        )

    if not candidates:
        return {
            "found": False, "kind": "", "target_id": "", "title": "",
            "score": 0.0, "matched": "", "start": None, "end": None,
            "content": "", "reason": "项目下没有可定位的标书正文(既无章节正文也无投标文件)",
        }

    best: dict | None = None
    for kind, tid, title, content, title_hit in candidates:
        local_score, local_span = 0.0, None
        for start, end, ptext in _paragraph_spans(content):
            if len(ptext.strip()) < 4:
                continue
            score = len(qb & _bigrams(ptext)) / max(1, len(qb)) + title_hit * 0.35
            if score > local_score:
                local_score, local_span = score, (start, end, ptext)
        if local_span and (best is None or local_score > best["score"]):
            best = {
                "kind": kind, "target_id": tid, "title": title, "content": content,
                "score": round(local_score, 3), "matched": local_span[2],
                "start": local_span[0], "end": local_span[1],
            }

    if best is None:
        kind, tid, title, content, _hit = candidates[0]
        return {
            "found": False, "kind": kind, "target_id": tid, "title": title,
            "score": 0.0, "matched": "", "start": None, "end": None, "content": content,
            "reason": "未能在正文中定位到对应段落,可整体追加到该正文",
        }
    best["found"] = True
    return best


async def _locate_fix_target(project, report, idx: int, db: AsyncSession) -> dict:
    """在标书正文里定位某条问题对应的段落。

    优先在章节正文里按"标题命中 + 段落相似度"定位;项目没有章节时退回投标文件正文。
    """
    plan = (report.results or {}).get(_FIX_PLAN_KEY) or {}
    fixes = plan.get("fixes") or []
    fix = next((f for f in fixes if str(f.get("idx")) == str(idx)), None)
    if fix is None:
        return {
            "found": False, "kind": "", "target_id": "", "title": "", "score": None,
            "matched": "", "start": None, "end": None, "content": "", "fix": None,
            "reason": (
                "这份报告还没有生成修复方案,请先点「一键生成修复方案」"
                if not fixes else f"修复方案里没有第 {idx} 条"
            ),
        }
    if fix.get("is_summary"):
        # 汇总行是整份文件多条内容的统计,不对应具体段落,不能拿去替换
        return {
            "found": False, "kind": "", "target_id": "", "title": "", "score": None,
            "matched": "", "start": None, "end": None, "content": "", "fix": fix,
            "reason": "这是「汇总行」,对应投标文件里多处内容,没有单一段落可以替换;请按这条整改文本到各章节分别修改。",
        }

    query = " ".join(
        str(fix.get(k) or "") for k in ("check_name", "problem", "where", "why")
    )
    loc = await _locate_in_project(project, query, str(fix.get("where") or ""), db)
    loc["fix"] = fix
    return loc


@router.get("/{project_id}/fix-locate")
async def locate_fix(
    project_id: str, report_id: str, idx: int, db: AsyncSession = Depends(get_db)
):
    """打开文本当前位置:返回命中段落及上下文,供前端高亮定位。"""
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    report = (
        await db.execute(select(CheckReport).where(CheckReport.id == report_id))
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")

    loc = await _locate_fix_target(project, report, idx, db)
    content = loc.pop("content", "") or ""
    fix = loc.pop("fix", {}) or {}
    return {
        "success": True,
        "locate": loc,
        "excerpt": _fix_excerpt(content, loc.get("start"), loc.get("end")),
        "fix_text": fix.get("fix_text") or "",
        "check_name": fix.get("check_name") or "",
    }


class _FixApplyBody(BaseModel):
    """一键替换的请求体。

    前端允许客户在弹窗里手动修改整改文本,所以这里收一个可选的 text;
    不传(或传空)时沿用模型生成的原文,保证旧调用方式完全兼容。

    mode 控制写入方式:
      - "replace"(默认):整段替换命中段落,原段落进备份;
      - "append":只在该段落末尾追加【整改补充】,一个字都不删。
        整改文本明显短于原文(说明它只是"补充几句话"而不是完整重写段落)时,
        前端会引导客户走 append,避免把原文里其它有效内容一起删掉。
    """

    text: str | None = None
    mode: str | None = None


@router.get("/{project_id}/fix-locate-all")
async def locate_fix_all(
    project_id: str, report_id: str, db: AsyncSession = Depends(get_db)
):
    """一次返回修复方案每条问题的"原文位置 + 原文段落",供弹窗做 黄(原文)/绿(新文) 对照。

    逐条调 fix-locate 也能做到,但 N 条问题就是 N 个请求;这里是纯本地文本检索
    (无模型调用),一次算完更省事,也不会把弹窗拖慢。
    """
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    report = (
        await db.execute(select(CheckReport).where(CheckReport.id == report_id))
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")

    plan = (report.results or {}).get(_FIX_PLAN_KEY) or {}
    fixes = plan.get("fixes") or []
    items: list[dict] = []
    for f in fixes:
        if not isinstance(f, dict):
            continue
        idx = f.get("idx")
        if idx is None:
            continue
        loc = await _locate_fix_target(project, report, idx, db)
        fix = loc.get("fix") or {}
        items.append({
            "idx": idx,
            "check_name": str(f.get("check_name") or ""),
            "found": bool(loc.get("found")),
            "title": str(loc.get("title") or ""),
            "target_type": str(loc.get("kind") or ""),
            "score": loc.get("score"),
            "old_text": str(loc.get("matched") or ""),
            "reason": str(loc.get("reason") or ""),
            "fix_text": str(fix.get("fix_text") or f.get("fix_text") or ""),
        })
    return {"success": True, "total": len(items), "items": items}


@router.post("/{project_id}/fix-apply")
async def apply_fix(
    project_id: str,
    report_id: str,
    idx: int,
    body: _FixApplyBody | None = None,
    db: AsyncSession = Depends(get_db),
):
    """一键替换:把整改文本写入标书对应位置(命中段落则替换,否则追加整改段)。

    body.text 非空时以它为准(客户手改后的内容),否则用模型生成的整改文本。
    """
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    report = (
        await db.execute(select(CheckReport).where(CheckReport.id == report_id))
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")

    loc = await _locate_fix_target(project, report, idx, db)
    if loc.get("fix") is None:
        raise HTTPException(status_code=400, detail=loc.get("reason") or "请先生成修复方案")
    fix = loc.get("fix") or {}
    model_text = str(fix.get("fix_text") or "").strip()
    edited_text = str(getattr(body, "text", "") or "").strip()
    fix_text = edited_text or model_text
    edited = bool(edited_text and edited_text != model_text)
    mode = str(getattr(body, "mode", "") or "replace").strip().lower()
    if mode not in ("replace", "append"):
        mode = "replace"
    if not fix_text:
        raise HTTPException(status_code=400, detail="该条修复方案没有可写入的整改文本")
    if not loc.get("target_id"):
        raise HTTPException(
            status_code=400,
            detail=loc.get("reason") or "没有找到可写入的标书正文",
        )

    old_content = loc.get("content") or ""
    old_len = len(loc.get("matched") or "")
    marker = f"\n【整改补充 · {fix.get('check_name') or '检查修复'}】\n{fix_text}\n"
    if mode == "append":
        # 只追加,一个字都不删:命中段落就插在该段落末尾,否则补到正文末尾
        if loc.get("found") and isinstance(loc.get("end"), int):
            insert_at = loc["end"] if loc["end"] > 0 else len(old_content)
            new_content = old_content[:insert_at] + marker + old_content[insert_at:]
            new_start = insert_at + 1
        else:
            insert_at = len(old_content)
            new_content = old_content + "\n" + marker
            new_start = insert_at + 3
        replaced = False
    elif loc.get("found") and isinstance(loc.get("start"), int):
        # 整段替换:命中段落整体换成整改文本(原段落已进备份)
        new_content = old_content[: loc["start"]] + fix_text + old_content[loc["end"]:]
        replaced = True
        new_start = loc["start"]
    else:
        new_content = old_content + "\n\n【整改补充 · " + (fix.get("check_name") or "检查修复") + "】\n" + fix_text + "\n"
        replaced = False
        new_start = len(old_content) + 2

    # 整段替换会把命中段落整体换掉:如果整改文本明显比原文短,说明它只是"补充几句话",
    # 直接替换会连原文里其它有效内容一起删掉,这里明确告诉前端,由客户选择换成"追加"。
    short_warning = ""
    if replaced and old_len and len(fix_text) < old_len * 0.7:
        short_warning = (
            f"整改文本只有 {len(fix_text)} 字,而将被替换掉的原文段落有 {old_len} 字"
            f"(少了 {old_len - len(fix_text)} 字)。这段新文本更像补充说明而不是完整段落,"
            "建议改用「追加到段落末尾」,或先在新文本里补全原文的关键信息再替换。"
        )

    from datetime import datetime as _dt

    if loc["kind"] == "chapter":
        row = (
            await db.execute(select(Chapter).where(Chapter.id == loc["target_id"]))
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="目标章节不存在")
        row.content = new_content
    else:
        row = (
            await db.execute(select(Document).where(Document.id == loc["target_id"]))
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="目标投标文件不存在")
        row.parsed_content = new_content

    # 原段落备份 + 操作留痕(存在报告的保留键里,导出报告时会被自动跳过)
    # ⚠️ 必须用 list(...) 造一个新列表:原先 dict(report.results) 只是浅拷贝,
    # history 依旧指向"已加载旧值"里的同一个列表,append 之后新旧值相等,
    # SQLAlchemy 认为 JSON 列没有变化 → 不发 UPDATE。实测后果:
    # 同一份报告只有第 1 次替换留下记录(那次是新建键),之后每次替换记录都静默丢失。
    results = dict(report.results or {})
    history = list(results.get(_FIX_APPLIED_KEY) or [])
    history.append({
        "time": _dt.now().isoformat(timespec="seconds"),
        "idx": idx,
        "check_name": fix.get("check_name") or "",
        "target_type": loc["kind"],
        "target_id": loc["target_id"],
        "target_title": loc["title"],
        "replaced": replaced,
        "mode": "replace" if replaced else "append",
        "before": loc.get("matched") or "",
        "after": fix_text,
        "model_text": model_text,
        "edited": edited,
        "old_len": old_len,
        "new_len": len(fix_text),
    })
    results[_FIX_APPLIED_KEY] = history
    report.results = results
    await db.commit()

    if replaced:
        message = (
            ("已把「你修改后的整改文本」整段替换到《{}》(原段落 {old} 字已备份,可在报告的修复记录里追溯)" if edited
             else "已把整改文本整段替换到《{}》(原段落 {old} 字已备份,可在报告的修复记录里追溯)")
        ).format(loc["title"], old=old_len)
    elif mode == "append" and loc.get("found"):
        message = (
            ("已把「你修改后的整改文本」追加到《{}》该段落末尾并标注【整改补充】(原文一字未删)" if edited
             else "已把整改文本追加到《{}》该段落末尾并标注【整改补充】(原文一字未删)")
        ).format(loc["title"])
    else:
        message = (
            ("未定位到精确段落,已把「你修改后的整改文本」追加到《{}》末尾并标注【整改补充】(原正文已备份)" if edited
             else "未定位到精确段落,已把整改文本追加到《{}》末尾并标注【整改补充】(原正文已备份)")
        ).format(loc["title"])

    return {
        "success": True,
        "applied": True,
        "replaced": replaced,
        "mode": "replace" if replaced else "append",
        "target_type": loc["kind"],
        "target_id": loc["target_id"],
        "target_title": loc["title"],
        "score": loc.get("score"),
        "before": (loc.get("matched") or "")[:300],
        "after": fix_text[:300],
        "edited": edited,
        "old_len": old_len,
        "new_len": len(fix_text),
        "short_warning": short_warning,
        "chars_before": len(old_content),
        "chars_after": len(new_content),
        "excerpt": _fix_excerpt(new_content, new_start, new_start + len(fix_text)),
        "message": message,
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
            # 必须带时区(iso_utc):库里是 naive UTC,裸 isoformat() 会被浏览器
            # 按当地时间解析,列表时间比真实时间早 8 小时。
            "created_at": iso_utc(r.created_at),
        }
        for r in reports
    ]}


@router.delete("/{project_id}/reports/{report_id}")
async def delete_check_report(project_id: str, report_id: str, db: AsyncSession = Depends(get_db)):
    """删除一份检查报告。

    报告的所有内容(检查明细、修复方案、已应用修复记录)都存在这一行的
    results JSON 里,删掉整行即连带清理;此外没有别的表引用 check_reports,
    所以不需要额外的级联处理。
    """
    result = await db.execute(
        select(CheckReport).where(
            CheckReport.id == report_id,
            CheckReport.project_id == project_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    report_type = report.type.value if isinstance(report.type, CheckType) else str(report.type)
    await db.delete(report)
    await db.commit()
    logger.info("[check] 删除检查报告 %s (type=%s, project=%s)", report_id, report_type, project_id)
    return {"success": True, "deleted": report_id, "type": report_type}


@router.post("/{project_id}/deposit")
async def check_deposit(project_id: str, db: AsyncSession = Depends(get_db)):
    project, tender_text, bid_text = await _get_tender_and_bid_text(project_id, db)
    from services.check.skills.deposit_check_skill import DepositCheckSkill
    gateway = _check_llm()
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

    # 分块读取并累计大小：一旦超过上限立即 413 中断，
    # 不再先把整个文件(可能是几个 GB)读进内存再判断
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限",
            )
        chunks.append(chunk)
    content_bytes = b"".join(chunks)

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
            # docx 是二进制格式：解析失败再按 UTF-8 硬解码只会得到乱码正文，
            # 这里明确报错，避免把垃圾内容送去给大模型
            logger.warning(f"[parse_uploaded_file] docx 解析失败: {e}")
            raise HTTPException(
                status_code=400,
                detail="文件解析失败，请确认是有效的 .docx/.pdf 文件",
            )
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
            except Exception as e:
                # pdfplumber 解析失败时继续尝试 fitz，但绝不把二进制当文本解码
                logger.warning(f"[parse_uploaded_file] pdfplumber 解析失败: {e}")

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
            except Exception as e:
                logger.warning(f"[parse_uploaded_file] fitz 解析失败: {e}")

            # 两个 PDF 库都不可用或都解析失败：明确报错，不再按 UTF-8 硬解码二进制
            raise HTTPException(
                status_code=400,
                detail="文件解析失败，请确认是有效的 .docx/.pdf 文件",
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # 未知后缀：只有内容确实是可解码的纯文本才回退，二进制一律报错
    try:
        return content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="文件解析失败，请确认是有效的 .docx/.pdf 文件",
        )


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

        gateway = _check_llm()

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

        if skill_result.success and not _is_meaningful(skill_result.data):
            # 模型偶尔只回 {"risk_level": "low"} / {"type": "json_object"} 这类空壳,
            # 原实现照样落库成"通过"报告 → 客户拿到一份"1 行、全是 —、却写 ✅通过"的空报告。
            # 这里直接判为失败,让前端提示重跑,不产出误导性报告。
            logger.warning(f"[single_check] {check_type} 返回内容为空,不保存报告")
            return {
                "success": False,
                "data": skill_result.data if isinstance(skill_result.data, dict) else {},
                "error": "本次检查未取得有效结果（模型返回内容为空），请重新运行该检查。",
                "warnings": skill_result.warnings,
            }

        if skill_result.success:
            check_enum = _CHECK_TYPE_TO_ENUM.get(check_type)
            if check_enum:
                risk_level = "low"
                if isinstance(skill_result.data, dict):
                    risk_level = str(
                        skill_result.data.get("risk_level")
                        or skill_result.data.get("overall_risk")
                        or "low"
                    )
                    # 与全面检查口径保持一致: has_critical_issues 同样算高风险。
                    # compliance / aiTextCheck / pricingLogic 等 skill 只设
                    # has_critical_issues、不产出 risk_level,原先单项检查会因此
                    # 错报"低风险",而全面检查却标成高风险(用户看到的口径不一致)。
                    if risk_level != "high" and skill_result.data.get("has_critical_issues"):
                        risk_level = "high"
                    # 回写,让轮询返回体与全面检查的徽章口径一致
                    skill_result.data["risk_level"] = risk_level
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

    gateway = _check_llm()

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

        # 全部检查项一次性并发会瞬间打出 15 路 LLM 请求，容易打满上游配额；
        # 这里用信号量限制最多 4 个检查项同时在跑(结果顺序仍与 check_types 一致)
        _upload_check_semaphore = asyncio.Semaphore(4)

        async def _run_upload_skill_limited(ct: str) -> tuple[str, dict]:
            async with _upload_check_semaphore:
                return await _run_upload_skill(ct)

        gather_results = await asyncio.gather(
            *[_run_upload_skill_limited(ct) for ct in check_types],
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
        # 这里绝不能再写 "import importlib"：函数内 import 会让 importlib 变成本函数的局部名，
        # 使上面的嵌套协程 _run_upload_skill 里的 importlib 变成未绑定的 free variable
        # (原先正是如此，导致 fullCheck 分支 15 个检查项 100% 报错)
        # 模块顶部已有全局 import importlib，直接用即可
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
    gateway = _check_llm()
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
    gateway = _check_llm()
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
    gateway = _check_llm()
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
    gateway = _check_llm()
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
    gateway = _check_llm()
    skill = MandatoryReqCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.MANDATORY, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}


_STATUS_CN = {
    "pass": "通过", "warning": "警告", "fail": "不通过",
    "high": "高风险", "medium": "中风险", "low": "低风险",
}


_CHECK_CN = {
    "compliance": "合规性检查", "disqualification": "废标项检查", "mandatoryReq": "强制性参数对照",
    "mandatory_req": "强制性参数对照", "qualification": "资质核查", "deposit": "保证金核查",
    "signature": "签章核查", "validity": "有效期核查", "pricing": "报价核查",
    "consistency": "一致性校验", "duplicate": "标书查重", "aiTextCheck": "AI文本检查",
    "ai_text_check": "AI文本检查", "docIntegrity": "文件完整性", "doc_integrity": "文件完整性",
    "pricingLogic": "报价逻辑闭环", "pricing_logic": "报价逻辑闭环", "riskScore": "风险评分",
    "risk_score": "风险评分", "formatCheck": "格式检查", "format": "格式检查",
    "technical": "技术方案", "commercial": "商务条款", "sampleReport": "样品/检测报告",
    "sample_report": "样品/检测报告", "jointBid": "联合投标协议", "joint_bid": "联合投标协议",
    "ebidSubmit": "电子投标提交", "ebid_submit": "电子投标提交", "selfcheck": "废标自查",
    "full_check": "全面检查", "fullCheck": "全面检查", "fitScore": "贴合度评分",
    "fit_score": "贴合度评分", "crossCheck": "交叉比对", "cross_check": "交叉比对",
    "scoreCoverage": "评分覆盖检查", "score_coverage": "评分覆盖检查",
}


def _check_cn(key: object) -> str:
    """返回「中文名称（内部代号）」。

    客户看不懂 full_check / pricing 这类内部代号,所以在中文名后面用括号补上代号,
    既好读又能和日志、接口对上号。
    """
    raw = str(getattr(key, "value", key) or "")
    if not raw:
        return "检查项"
    cn = _CHECK_CN.get(raw) or _CHECK_CN.get(raw.replace("_", "").lower())
    if not cn:
        return raw
    return cn if cn == raw else f"{cn}（{raw}）"


def _is_check_envelope(results: object) -> bool:
    """full_check 的结果是信封结构 {检查名: {success, data, error}}。"""
    if not isinstance(results, dict) or not results:
        return False
    # 跳过内部保留键(如 __fix_plan__),否则修复方案会被误当成一个检查项
    return all(
        isinstance(v, dict) and "success" in v
        for k, v in results.items()
        if not str(k).startswith("__")
    )


# 单检查结果里可逐条展开的明细列表键名(按优先级)
_CHECK_ITEM_KEYS = (
    "items", "findings", "issues", "problems", "clauses", "details",
    "missing_items", "risks", "duplicates", "checks", "records",
)
# 只用于描述"检查本身"的字段,不构成有效检查内容
_META_KEYS = {
    "risk_level", "overall_risk", "has_critical_issues", "type", "success", "error",
    "message", "raw_text", "model", "usage", "status", "summary", "format",
    "generated_at", "project_id", "created_at",
}
# 明细项显式状态 → 报告状态
_ITEM_STATUS_CN = {
    "compliant": "pass", "pass": "pass", "passed": "pass", "ok": "pass", "yes": "pass",
    "符合": "pass", "通过": "pass", "无需修改": "pass", "no_issue": "pass",
    "non_compliant": "fail", "noncompliant": "fail", "not_compliant": "fail",
    "fail": "fail", "failed": "fail", "no": "fail", "missing": "fail",
    "不符合": "fail", "不通过": "fail", "未响应": "fail", "缺失": "fail",
    "partial": "warning", "partially_compliant": "warning", "partial_compliant": "warning",
    "warning": "warning", "warn": "warning", "注意": "warning", "需注意": "warning",
    "部分符合": "warning", "部分响应": "warning",
}


def _first_item_list(data: dict) -> tuple[str, list]:
    """从单检查结果里找出可逐条展开的明细列表。"""
    if not isinstance(data, dict):
        return "", []
    for key in _CHECK_ITEM_KEYS:
        val = data.get(key)
        if isinstance(val, list):
            rows = [x for x in val if isinstance(x, dict)]
            if rows:
                return key, rows
    return "", []


def _counter_line(data: dict) -> str:
    """把计数类字段拼成一句人话,替代表格里的 '—'。"""
    if not isinstance(data, dict):
        return ""
    parts: list[str] = []
    for key, tpl in (
        ("total_requirements", "招标要求共{v}条"),
        ("total_clauses", "招标条款共{v}条"),
        ("total_mandatory", "强制项共{v}条"),
        ("total_checks", "检查项共{v}条"),
        ("total_items", "问题共{v}条"),
        ("compliant", "符合{v}条"),
        ("passed", "通过{v}条"),
        ("non_compliant", "不符合{v}条"),
        ("failed", "未通过{v}条"),
        ("partial", "部分响应{v}条"),
        ("missing", "缺失{v}条"),
        ("unresponded", "未响应{v}条"),
        ("warning", "需注意{v}条"),
        ("coverage_rate", "覆盖率{v}"),
    ):
        v = data.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            parts.append(tpl.format(v=v))
    return "，".join(parts)


_SUMMARY_KEY_CN = {
    "total": "共", "passed": "通过", "failed": "不通过", "warning": "需注意",
    "critical": "严重", "major": "重要", "minor": "轻微",
    "rule_based": "规则命中", "llm_based": "模型判定",
    "found": "命中", "missing": "缺失",
}

_SCALAR_CN = {
    "composite_score": "综合风险分(0-100)",
    "duplicate_score": "查重相似度(0-100)",
    "max_similarity": "最高相似度",
    "coverage_rate": "覆盖率",
    "risk_level": "风险等级",
    "overall_risk": "总体风险",
    "method": "判定方式",
    "disqualification_risk": "存在废标风险",
    "has_critical_issues": "存在严重问题",
}

_RISK_LEVEL_CN = {
    "high": "高", "medium": "中", "low": "低", "critical": "严重", "none": "无",
}


def _summary_dict_line(data: dict) -> str:
    """把 {"total":4,"passed":1,"warning":3} 这类汇总字典翻成人话。

    全面检查里不少技能只回一个 summary 字典(没有明细列表),旧实现
    直接渲染成"—",客户看到的就是一整行占位符。
    """
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, dict):
        return ""
    total = None
    bits: list[str] = []
    for k, v in summary.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        cn = _SUMMARY_KEY_CN.get(str(k))
        if not cn:
            continue
        if str(k) == "total":
            total = int(v)
        else:
            bits.append(f"{cn} {int(v)}")
    if total is not None and bits:
        return f"共 {total} 项：" + "、".join(bits)
    if bits:
        return "、".join(bits)
    return ""


def _scalar_line(data: dict, limit: int = 4) -> str:
    """枚举结果里的分数/风险/布尔字段,给"没有明细列表"的检查一个有内容的"实际"值。"""
    if not isinstance(data, dict):
        return ""
    bits: list[str] = []

    def _add(key: str, value: object) -> None:
        cn = _SCALAR_CN.get(key)
        if not cn or len(bits) >= limit:
            return
        if isinstance(value, bool):
            bits.append(f"{cn}：{'是' if value else '否'}")
        elif isinstance(value, (int, float)):
            bits.append(f"{cn}：{round(float(value), 1)}")
        elif isinstance(value, str) and value:
            bits.append(f"{cn}：{_RISK_LEVEL_CN.get(value.lower(), value[:20])}")

    for key, value in data.items():
        if str(key).startswith("__") or key in _META_KEYS or key in _CHECK_ITEM_KEYS or key == "summary":
            continue
        if isinstance(value, dict):
            # duplicate: {"internal_duplicate": {"found": false, "max_similarity": 0.0}}
            if isinstance(value.get("max_similarity"), (int, float)):
                found = value.get("found")
                label = {"internal_duplicate": "内部查重", "external_similarity": "外部相似"}.get(str(key), str(key))
                bits.append(
                    f"{label}：最高相似度 {round(float(value['max_similarity']), 1)}"
                    + ("（发现重复）" if found else "（未发现重复）" if found is False else "")
                )
            continue
        _add(str(key), value)
    return "；".join(bits[:limit])


def _payload_line(data: dict) -> str:
    """汇总字典 → 计数行 → 分数/风险字段,依次兜底,尽量不留空。"""
    return _summary_dict_line(data) or _counter_line(data) or _scalar_line(data)


def _is_meaningful(data: object) -> bool:
    """判断检查结果是否真的包含有效内容。

    空壳结果(如模型只回了 {"risk_level": "low"} 或 {"type": "json_object"})
    以前会被当成"通过"写进报告,客户看到的是一份"1 行、全是 —、却写着 ✅ 通过"
    的空报告,属于误导。这类结果一律判为"未评估"。
    """
    if not isinstance(data, dict):
        return bool(data)
    if data.get("error"):
        return False
    if str(data.get("status") or "").lower() in ("error", "failed", "failure"):
        return False
    if _first_item_list(data)[1]:
        return True
    if _counter_line(data):
        return True
    return any(
        k not in _META_KEYS and v not in (None, "", [], {}, 0)
        for k, v in data.items()
    )


def _item_status(data: dict, success: bool) -> str:
    if not success:
        return "fail"
    if not isinstance(data, dict):
        return "unknown"
    # 明细项常带显式结论(compliant / non_compliant / partial),优先采信;
    # 原实现只看 risk_level,会把 non_compliant 的条款误报成"通过"。
    raw = str(
        data.get("status") or data.get("result") or data.get("conclusion") or ""
    ).strip().lower()
    if raw in _ITEM_STATUS_CN:
        return _ITEM_STATUS_CN[raw]
    if not _is_meaningful(data):
        return "unknown"
    rl = str(data.get("risk_level") or data.get("overall_risk") or "").lower()
    if data.get("has_critical_issues") or rl == "high":
        return "fail"
    if rl == "medium":
        return "warning"
    return "pass"


def _readable_detail(data: dict) -> str:
    for key in ("detail", "summary", "message", "description", "reason", "conclusion", "overall"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:300]
    bits = []
    for key, label in (
        ("missing", "未响应条数"), ("total_clauses", "条款总数"), ("total", "总计"),
        ("passed", "通过"), ("failed", "未通过"), ("warning", "警告"),
        ("score", "得分"), ("risk_score", "风险分"), ("total_items", "问题总数"),
    ):
        if isinstance(data.get(key), (int, float)):
            bits.append(f"{label} {data[key]}")
    return "；".join(bits)


def _readable_suggestions(data: dict) -> str:
    sugs = (
        data.get("suggestions") or data.get("recommendations") or data.get("fixes")
        or data.get("actions") or data.get("suggestion") or data.get("fix") or data.get("advice")
    )
    if isinstance(sugs, str):
        return sugs.strip()[:500]
    if isinstance(sugs, list):
        out: list[str] = []
        for s in sugs:
            if isinstance(s, str):
                out.append(s.strip())
            elif isinstance(s, dict):
                out.append(str(s.get("title") or s.get("description") or s.get("text") or s.get("content") or "").strip())
        return "；".join([t for t in out if t])[:800]
    return ""


def _report_to_checks(results: object, risk_level: object = None, report_type: object = None) -> dict:
    """把 CheckReport.results 规范化成报告渲染需要的 {checks, summary, risk_level}。

    原先 /reports/{id}/content 与 /export 直接把 full_check 的信封结构
    ({检查名: {success, data, error}}) 当 report_data 传给渲染技能,而渲染端取
    data["checks"] 取不到 → 只剩表头、风险等级 unknown 的空模板(用户反馈的
    "点开只有一样的模板、没有解决方法")。这里补齐检查项明细,并把每条具体问题
    拆成独立的"不通过项详情",带上修改建议。
    """
    rl = str(getattr(risk_level, "value", risk_level) or "").lower()
    checks: list[dict] = []

    if _is_check_envelope(results):
        for key, val in results.items():  # type: ignore[union-attr]
            if str(key).startswith("__"):
                continue
            inner = val.get("data") if isinstance(val.get("data"), dict) else {}
            ok = bool(val.get("success"))
            cn_key = _check_cn(key)
            status = _item_status(inner, ok)
            payload_line = _payload_line(inner)
            detail = _readable_detail(inner) or payload_line
            suggestions = _readable_suggestions(inner)
            _, items = _first_item_list(inner)

            if not ok:
                checks.append({
                    "check_name": cn_key,
                    "status": "fail",
                    "detail": "该项检查执行失败,请重新执行全面检查",
                    "suggestion": "请在下方单独重跑该项检查;确认招标/投标文本完整后再执行全面检查。",
                    "required": "见招标文件对应条款",
                    "actual": "执行失败",
                })
                continue

            if not items:
                # 没有明细列表的技能(查重/风险评分/一致性这类算法结果):用汇总、分数、
                # 风险字段把"实际/说明"填实,不再输出"见招标文件对应条款 | — | (空)"
                # 这种只有占位符的行(用户最初反馈的就是这种行)
                checks.append({
                    "check_name": cn_key,
                    "status": status,
                    "detail": detail or "该项检查已完成，未返回可逐条展示的明细。",
                    "suggestion": suggestions,
                    "required": "见招标文件对应条款",
                    "actual": (payload_line or detail or "已完成")[:200],
                })
                continue

            # 有明细列表:先出"汇总行",再逐条展开(与单项检查报告同一口径)
            summary_idx = len(checks)
            checks.append({
                "check_name": f"{cn_key}（汇总）",
                "status": status,
                "detail": "",
                "suggestion": suggestions,
                "required": "见招标文件对应条款",
                "actual": (payload_line or f"共核对 {len(items)} 条明细")[:200],
                "is_summary": True,
                "item_count": len(items),
            })
            for it in items[:30]:
                if not isinstance(it, dict):
                    continue
                title = (
                    it.get("check_name") or it.get("certificate_name") or it.get("title")
                    or it.get("clause_title") or it.get("clause_id") or it.get("check_type")
                    or it.get("issue") or it.get("description") or "明细项"
                )
                sug = (
                    it.get("suggestion") or it.get("fix") or it.get("recommendation")
                    or it.get("advice") or it.get("action") or ""
                )
                # 各类技能的明细字段:废标项 clause_id/clause_content/response_content/
                # response_quality/response_found;资质 required_by_tender/certificate_name;
                # 有效期 required_period/actual_period;保证金 required/actual
                quality = str(it.get("response_quality") or "").strip()
                found = it.get("response_found")
                parts: list[str] = []
                if quality:
                    parts.append(f"响应质量：{quality}")
                if found is False:
                    parts.append("投标文件中未找到对应响应")
                if not parts:
                    parts.append(str(
                        it.get("detail") or it.get("description") or it.get("reason")
                        or "该条款需要人工复核"
                    ))
                ctype = str(it.get("clause_type") or "").strip()
                if ctype:
                    parts.append(f"条款类型：{ctype}")
                st = _item_status(it, True)
                if st == "unknown":
                    st = "fail" if found is False else "warning"
                loc = str(it.get("source_location") or it.get("location") or "")
                if loc:
                    parts.append(f"招标出处：{loc}")
                rloc = str(it.get("response_location") or "")
                if rloc:
                    parts.append(f"投标出处：{rloc}")
                req = str(
                    it.get("clause_content") or it.get("requirement") or it.get("required")
                    or it.get("required_by_tender") or it.get("clause_text")
                    or it.get("required_period") or ""
                )
                act = str(
                    it.get("response_content") or it.get("actual") or it.get("response")
                    or it.get("actual_period") or ""
                )
                checks.append({
                    "check_name": f"{cn_key} - {str(title)[:50]}",
                    "status": st,
                    "detail": "；".join(parts)[:300],
                    "suggestion": str(sug)[:300],
                    "required": req[:200] or "见招标文件对应条款",
                    "actual": act[:200] or ("未响应" if st != "pass" else "已响应"),
                })

            # 回填该技能汇总行的统计:数字直接数明细行,保证与结论/概要一致
            _rows = checks[summary_idx + 1:]
            _bits = []
            for _st, _label in (("pass", "通过"), ("fail", "不通过"), ("warning", "需注意"), ("unknown", "未评估")):
                _n = sum(1 for _c in _rows if _c.get("status") == _st)
                if _n:
                    _bits.append(f"{_label} {_n}")
            checks[summary_idx]["detail"] = (
                f"共逐条核对 {len(_rows)} 条：{'、'.join(_bits)}；逐条结果与出处见下方各行。"
            )
            if len(items) > len(_rows):
                checks.append({
                    "check_name": f"{cn_key}（其余明细未逐条列出）",
                    "status": "warning",
                    "detail": (
                        f"该项共检出 {len(items)} 条明细，报告表格仅列出前 {len(_rows)} 条，"
                        f"另有 {len(items) - len(_rows)} 条请在「投标检查」页面查看。"
                    ),
                    "suggestion": "如需完整逐条明细，请在系统页面的检查结果中查看。",
                    "required": "—",
                    "actual": f"另有 {len(items) - len(_rows)} 条未列出",
                    "is_summary": True,
                })
    elif isinstance(results, dict) and isinstance(results.get("checks"), list):
        checks = [c for c in results["checks"] if isinstance(c, dict)]  # type: ignore[union-attr]
        if not rl:
            rl = str(results.get("risk_level") or "").lower()
    elif isinstance(results, dict):
        # 单项检查报告:先把底层明细逐条展开成表格行。
        # 原实现只输出 1 行汇总,明明库里存了 27 条"要求/实际/状态/建议",
        # 报告上却只看到"见招标文件对应条款 | — | ❌不通过 | (空)"(用户反馈可读性不高)。
        ok = results.get("success", True) is not False
        cn_name = _check_cn(report_type or "检查项")
        detail = _readable_detail(results)
        suggestions = _readable_suggestions(results)
        counters = _counter_line(results)
        _, items = _first_item_list(results)

        if items and ok:
            summary_idx = len(checks)
            checks.append({
                "check_name": f"{cn_name}（汇总）",
                "status": _item_status(results, ok),
                "detail": "",  # 逐条展开后回填,保证与明细行统计严格一致
                "suggestion": suggestions,
                "required": "见招标文件对应条款",
                "actual": counters or (detail[:120] if detail else f"共核对 {len(items)} 条明细"),
                "is_summary": True,
                "item_count": len(items),
            })
            for it in items[:60]:
                title = str(
                    it.get("title") or it.get("clause_title") or it.get("clause_id")
                    or it.get("requirement") or it.get("item") or it.get("name")
                    or it.get("issue") or it.get("description") or "明细项"
                )
                req = str(
                    it.get("requirement") or it.get("clause_content") or it.get("clause_text")
                    or it.get("tender_requirement") or it.get("required") or it.get("expect") or ""
                )
                act = str(
                    it.get("response") or it.get("response_content") or it.get("actual")
                    or it.get("bid_content") or it.get("current") or ""
                )
                sug = str(
                    it.get("suggestion") or it.get("fix") or it.get("recommendation")
                    or it.get("advice") or it.get("action") or ""
                )
                loc = str(it.get("source_location") or it.get("location") or "")
                rloc = str(it.get("response_location") or "")
                quality = str(it.get("response_quality") or "")
                st = _item_status(it, True)
                sev = str(it.get("severity") or it.get("risk_level") or "").lower()
                if st == "unknown":
                    st = "warning"
                note: list[str] = []
                if sug:
                    note.append(sug)
                elif st == "pass":
                    note.append("无需修改")
                elif st == "fail":
                    note.append("该条未满足招标要求,须在提交前补正")
                else:
                    note.append("建议人工复核该条")
                # 结论为"符合"但被标注 critical/未找到响应时给个醒目提醒,
                # 但不改判状态 —— 否则结论里的"通过 N 条"会和统计口径对不上
                if st == "pass" and (sev in ("critical", "high") or it.get("response_found") is False):
                    note.append("⚠️ 该条虽判为符合，但被标记为严重/未找到响应，建议复核")
                if quality:
                    note.append(f"响应质量：{quality}")
                if it.get("response_found") is False and "未找到响应" not in "；".join(note):
                    note.append("投标文件中未找到对应响应")
                if loc:
                    note.append(f"招标出处：{loc}")
                if rloc:
                    note.append(f"投标出处：{rloc}")
                checks.append({
                    "check_name": title[:70],
                    "status": st,
                    "detail": "；".join(note)[:400],
                    "suggestion": sug[:300],
                    "required": req[:300] or "见招标文件对应条款",
                    "actual": act[:300] or ("未响应" if st != "pass" else "已响应"),
                })

            # 回填汇总行:数字直接数明细行,避免"共核对 27 条"与概要/结论对不上
            _rows = checks[summary_idx + 1:]
            _bits = []
            for _st, _label in (("pass", "通过"), ("fail", "不通过"), ("warning", "需注意")):
                _n = sum(1 for _c in _rows if _c.get("status") == _st)
                if _n:
                    _bits.append(f"{_label} {_n}")
            checks[summary_idx]["detail"] = (
                f"共逐条核对 {len(_rows)} 条明细：" + "、".join(_bits) + "；逐条结果见下方各行。"
            )
            if len(items) > len(_rows):
                # 明细过多时明确说明截断,不能让客户以为这就是全部
                checks.append({
                    "check_name": "（其余明细未逐条列出）",
                    "status": "warning",
                    "detail": (
                        f"本次共检出 {len(items)} 条明细，报告表格仅列出前 {len(_rows)} 条，"
                        f"另有 {len(items) - len(_rows)} 条请在「投标检查」页面查看完整明细。"
                    ),
                    "suggestion": "如需完整逐条明细，请在系统页面的检查结果中查看。",
                    "required": "—",
                    "actual": f"另有 {len(items) - len(_rows)} 条未列出",
                    "is_summary": True,
                })
        elif not _is_meaningful(results):
            # 空壳结果:必须明确写"未评估",绝不能显示成"通过"
            checks.append({
                "check_name": cn_name,
                "status": "unknown",
                "detail": "本次检查未取得有效结果（模型返回内容为空），无法判定是否通过，请重新运行该项检查。",
                "suggestion": "请重新执行该检查；若仍为空，请先在「系统设置」确认默认模型可用后再试。",
                "required": "见招标文件对应条款",
                "actual": "未取得有效检查数据",
            })
        else:
            checks.append({
                "check_name": cn_name,
                "status": _item_status(results, ok),
                "detail": detail,
                "suggestion": suggestions,
                "required": "见招标文件对应条款",
                "actual": counters or detail[:120] or "—",
            })

    # 统计口径:汇总行只是"目录",不计入 通过/不通过/需注意 的条数,
    # 否则"共检查 28 项"会和详情里的"26 条要求"对不上,客户看着糊涂。
    item_mode = any(c.get("is_summary") for c in checks)
    counted = [c for c in checks if not c.get("is_summary")] or checks
    failed = sum(1 for c in counted if c.get("status") == "fail")
    passed = sum(1 for c in counted if c.get("status") == "pass")
    warning = sum(1 for c in counted if c.get("status") == "warning")
    unknown = sum(1 for c in counted if c.get("status") == "unknown")
    return {
        "checks": checks,
        "summary": {
            "total": len(counted),
            "passed": passed,
            "failed": failed,
            "warning": warning,
            "unknown": unknown,
            "item_mode": item_mode,
        },
        "risk_level": rl or ("high" if failed else "low"),
    }


def _build_check_report_docx(project_name: str, results: dict, risk_level: str, generated_at: str) -> bytes:
    """把检查报告结果渲染成真正的 Word(.docx) 字节流。

    原先 /reports/{id}/export 不管 format 传什么,都返回 markdown 纯文本,
    前端下载到的"Word"其实是一段 markdown,用 Word 打不开。
    """
    import io as _io

    from docx import Document as _Docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH as _ALIGN
    from docx.shared import Cm as _Cm
    from docx.shared import Pt as _Pt

    doc = _Docx()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = _Cm(21.0), _Cm(29.7)
    sec.top_margin = sec.bottom_margin = _Cm(2.54)
    sec.left_margin = sec.right_margin = _Cm(3.17)

    head = doc.add_paragraph()
    head.alignment = _ALIGN.CENTER
    run = head.add_run("投标文件检查报告")
    run.bold = True
    run.font.size = _Pt(20)

    meta = doc.add_paragraph()
    meta.alignment = _ALIGN.CENTER
    meta.add_run(
        f"项目名称：{project_name}\n"
        f"总体风险等级：{_STATUS_CN.get(str(risk_level), risk_level)}\n"
        f"生成时间：{generated_at}"
    )
    doc.add_page_break()

    # 中文字体统一走 eastAsia,否则 Word 里中文会回落到默认字体、数字却是西文字体
    try:
        from docx.oxml.ns import qn as _qn

        normal = doc.styles["Normal"]
        normal.font.name = "Times New Roman"
        normal.font.size = _Pt(10.5)
        rfonts = normal._element.get_or_add_rPr().get_or_add_rFonts()
        rfonts.set(_qn("w:ascii"), "Times New Roman")
        rfonts.set(_qn("w:hAnsi"), "Times New Roman")
        rfonts.set(_qn("w:eastAsia"), "宋体")
    except Exception:
        pass

    # 统一成与 Markdown/HTML 完全一致的数据口径,不再把原始 JSON 倒出来
    report = _report_to_checks(results, risk_level, None)
    checks = [c for c in (report.get("checks") or []) if isinstance(c, dict)]
    summary = report.get("summary") or {}
    status_cn = {"pass": "通过", "fail": "不通过", "warning": "需注意", "unknown": "未评估"}
    fatal_keys = ("废标", "资格", "否决", "无效投标", "实质性", "保证金", "密封", "签章")

    def _t(value: object, limit: int = 300) -> str:
        return str(value if value is not None else "").replace("\n", " ").strip()[:limit]

    fail_items = [c for c in checks if c.get("status") == "fail"]
    fatal = [
        c
        for c in fail_items
        if any(
            k in f"{c.get('check_name', '')}{c.get('check_type', '')}{c.get('required', '')}"
            for k in fatal_keys
        )
    ]

    if not checks:
        # 兜底:统一映射拿不到条目时也绝不生成空文档
        doc.add_heading("原始检查数据", level=1)
        for key, value in (results or {}).items():
            doc.add_paragraph(f"{key}：{_t(value, 1200)}")
    else:
        doc.add_heading("一句话结论", level=1)
        doc.add_paragraph(
            f"本次共检查 {summary.get('total', len(checks))} 项："
            f"通过 {summary.get('passed', 0)} 项，"
            f"不通过 {summary.get('failed', len(fail_items))} 项，"
            f"需注意 {summary.get('warning', 0)} 项。"
        )
        if fatal:
            doc.add_paragraph(
                f"其中 {len(fatal)} 项可能直接导致废标或资格审查不通过，必须在提交前优先修改，"
                "否则投标文件存在被否决的风险。"
            )
        elif fail_items:
            doc.add_paragraph(
                "未发现直接导致废标的条款，但不通过项会影响评分或需要补正，建议提交前逐项修改。"
            )
        else:
            doc.add_paragraph("未发现不通过项，可以按正常流程提交。")

        picks = [
            c for c in fail_items if _t(c.get("required"), 12) not in ("", "—", "-", "见招标文件对应条款")
        ] or fail_items
        if picks:
            doc.add_heading("建议优先修改的前 3 项", level=2)
            for i, c in enumerate(picks[:3], 1):
                name = c.get("check_name") or c.get("check_type") or "未命名检查项"
                para = doc.add_paragraph()
                para.add_run(f"{i}. {name}").bold = True
                req = _t(c.get("required"), 200)
                act = _t(c.get("actual"), 200)
                fix = _t(c.get("suggestion"), 200)
                if not fix or any(k in fix for k in ("条数", "条款总数", "共检查")):
                    fix = "按招标文件要求补充或修正对应内容"
                if req:
                    doc.add_paragraph(f"招标要求：{req}", style="List Bullet")
                if act:
                    doc.add_paragraph(f"我方现状：{act}", style="List Bullet")
                doc.add_paragraph(f"怎么改：{fix}", style="List Bullet")

        # 5 列明细表:Word 真表格(原先只有段落,列项挤在一起)
        doc.add_heading("检查结果明细", level=1)
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        for idx, title in enumerate(("检查项", "要求", "实际", "状态", "说明")):
            cell = table.rows[0].cells[idx]
            cell.text = ""
            run = cell.paragraphs[0].add_run(title)
            run.bold = True
        for c in checks:
            row = table.add_row().cells
            status = str(c.get("status", "unknown"))
            row[0].text = _t(c.get("check_name") or c.get("check_type"), 60)
            row[1].text = _t(c.get("required"), 400)
            row[2].text = _t(c.get("actual"), 400)
            row[3].text = status_cn.get(status, status)
            row[4].text = _t(c.get("detail") or c.get("suggestion"), 400)
        doc.add_paragraph("")

        if fail_items:
            doc.add_heading("不通过项详情与修改建议", level=1)
            for i, c in enumerate(fail_items, 1):
                name = c.get("check_name") or c.get("check_type") or "未命名检查项"
                doc.add_heading(f"{i}. {name}", level=2)
                for label, key in (
                    ("招标要求", "required"),
                    ("我方现状", "actual"),
                    ("说明", "detail"),
                    ("修改建议", "suggestion"),
                ):
                    val = _t(c.get(key), 600)
                    if val:
                        doc.add_paragraph(f"{label}：{val}")

    buf = _io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@router.get("/{project_id}/reports/{report_id}/export")
async def export_check_report(
    project_id: str,
    report_id: str,
    format: str = "markdown",
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import PlainTextResponse, Response

    # 报告必须属于 URL 里的 project_id，避免跨项目读取他人的检查报告
    result = await db.execute(
        select(CheckReport).where(
            CheckReport.id == report_id,
            CheckReport.project_id == project_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="检查报告不存在")

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    project_name = project.name if project else "未命名项目"

    # docx/doc/word → 返回真正的 Word 二进制,不再返回 markdown 文本
    if format.lower() in ("docx", "doc", "word"):
        import re as _re
        from urllib.parse import quote as _quote

        data = _build_check_report_docx(
            project_name,
            report.results or {},
            report.risk_level or "unknown",
            # docx 里给人看的时间:库里是 UTC,要转成本地(否则导出的文档比真实时间早 8 小时)
            local_str(report.created_at),
        )
        safe = _re.sub(r'[\\/:*?"<>|]', "_", project_name)[:60] or "report"
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(safe + '_检查报告.docx')}"},
        )

    from services.check.skills.check_report_export_skill import CheckReportExportSkill
    from services.llm_factory import get_llm_gateway

    gateway = _check_llm()
    skill = CheckReportExportSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "report_data": _report_to_checks(report.results, report.risk_level, report.type),
            "format": format,
            "project_name": project_name,
            # 报告正文里的"生成时间"统一用报告创建时间(本地时区)：
            # 原先用"此刻"，导致列表/预览/导出三处时间各不相同
            "report_time": local_str(report.created_at),
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

    # 与导出端点同样口径：报告必须属于 URL 里的 project_id，避免跨项目预览他人报告
    result = await db.execute(
        select(CheckReport).where(
            CheckReport.id == report_id,
            CheckReport.project_id == project_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="检查报告不存在")

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

    gateway = _check_llm()
    skill = CheckReportExportSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "report_data": _report_to_checks(report.results, report.risk_level, report.type),
            "format": format,
            "project_name": project_name,
            # 报告正文里的"生成时间"统一用报告创建时间(本地时区)：
            # 原先用"此刻"，导致列表/预览/导出三处时间各不相同
            "report_time": local_str(report.created_at),
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
    gateway = _check_llm()
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
    gateway = _check_llm()
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
    ctx = SkillContext(project_id=project_id, db=db, llm=_check_llm(), parameters={"check_results": check_results})
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
    gateway = _check_llm()
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
    gateway = _check_llm()
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
    gateway = _check_llm()
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
    gateway = _check_llm()
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
    gateway = _check_llm()
    skill = PricingLogicCheckSkill()
    ctx = SkillContext(project_id=project_id, db=db, llm=gateway, parameters={"tender_text": tender_text, "bid_text": bid_text})
    skill_result = await skill.safe_execute(ctx)
    if skill_result.success:
        report = CheckReport(project_id=project.id, type=CheckType.PRICING_LOGIC, results=skill_result.data, risk_level=skill_result.data.get("risk_level", "low"))
        db.add(report)
        await db.flush()
    return {"success": skill_result.success, "data": skill_result.data, "error": skill_result.error, "warnings": skill_result.warnings}
