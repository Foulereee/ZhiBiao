from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import Project, Document, Analysis, Outline, Chapter, ProjectStatus
from services.llm_factory import get_llm_gateway
from core.skill_engine.base import SkillContext
from core.task_manager import TaskManager

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────
# 异步任务端点
# ─────────────────────────────────────────────

@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """查询异步任务状态"""
    tm = TaskManager.instance()
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.to_dict()


# ─────────────────────────────────────────────
# 大纲生成（异步任务模式）
# ─────────────────────────────────────────────

async def _do_generate_outline(project_id: str, mode: str):
    """大纲生成的实际执行逻辑（在后台任务中运行）"""
    from services.database import async_session

    session_factory = async_session()
    async with session_factory() as db:
        try:
            t0 = time.monotonic()
            logger.info(f"[大纲生成] 开始 project_id={project_id}, mode={mode}")

            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                return {"success": False, "error": "项目不存在"}

            doc_result = await db.execute(
                select(Document).where(Document.id == project.tender_doc_id)
            )
            doc = doc_result.scalar_one_or_none()
            if not doc or not doc.parsed_content:
                return {"success": False, "error": "请先解析招标文件"}

            logger.info(f"[大纲生成] DB查询完成 耗时={time.monotonic()-t0:.2f}s, "
                        f"文档长度={len(doc.parsed_content)}字符")

            analysis_result = await db.execute(
                select(Analysis).where(Analysis.project_id == project.id)
            )
            analysis = analysis_result.scalar_one_or_none()

            scoring_matrix = {}
            if analysis and analysis.scoring_matrix:
                scoring_matrix = analysis.scoring_matrix
            elif analysis and analysis.dimensions:
                scoring_dim = analysis.dimensions.get("scoring", {})
                if scoring_dim and isinstance(scoring_dim, dict):
                    scoring_items = scoring_dim.get("scoring_items", scoring_dim.get("evaluation细则", []))
                    if scoring_items and isinstance(scoring_items, list):
                        scoring_matrix = {"rows": [
                            {
                                "category": item.get("name", item.get("category", "")),
                                "item": item.get("name", item.get("description", item.get("item", ""))),
                                "score": item.get("score", item.get("max_score", 0)),
                            }
                            for item in scoring_items if isinstance(item, dict)
                        ]}

            from services.generate.skills.outline_gen_skill import OutlineGenSkill

            gateway = get_llm_gateway()
            skill = OutlineGenSkill()
            ctx = SkillContext(
                project_id=project_id,
                db=db,
                llm=gateway,
                parameters={
                    "mode": mode,
                    "document_text": doc.parsed_content,
                    "scoring_matrix": scoring_matrix,
                },
            )

            logger.info(f"[大纲生成] 调用Skill, model={gateway.default_model}")
            skill_result = await skill.safe_execute(ctx)

            logger.info(f"[大纲生成] Skill完成, 耗时={time.monotonic()-t0:.1f}s, "
                        f"success={skill_result.success}")

            if skill_result.success:
                outline_data = skill_result.data.get("outline", {})
                score_mapping = outline_data.get("score_mapping", {}) if isinstance(outline_data, dict) else {}
                chapters = outline_data.get("chapters", []) if isinstance(outline_data, dict) else []

                if not chapters:
                    return {"success": False, "error": "大纲生成结果为空，请重试"}

                existing = await db.execute(
                    select(Outline).where(Outline.project_id == project.id)
                )
                outline = existing.scalar_one_or_none()
                if outline:
                    outline.mode = mode
                    outline.tree = outline_data
                    outline.score_mapping = score_mapping
                else:
                    outline = Outline(
                        project_id=project.id,
                        mode=mode,
                        tree=outline_data,
                        score_mapping=score_mapping,
                    )
                    db.add(outline)

                project.status = ProjectStatus.OUTLINING.value
                await db.commit()

            return {
                "success": skill_result.success,
                "data": skill_result.data,
                "error": skill_result.error,
                "warnings": skill_result.warnings,
            }
        except Exception as e:
            logger.error(f"[大纲生成] 异常: {e}")
            return {"success": False, "error": str(e)}


@router.post("/{project_id}/outline")
async def generate_outline(
    project_id: str,
    mode: str = "aligned",
    db: AsyncSession = Depends(get_db),
):
    """大纲生成（异步任务模式）。

    立即返回 task_id，前端通过 GET /generate/task/{task_id} 轮询结果。
    兼容模式：如果请求带 ?sync=1 则走同步模式（调试用）。
    """
    # 快速校验
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")

    # 提交异步任务
    tm = TaskManager.instance()
    task = await tm.submit("outline_gen", _do_generate_outline, project_id, mode)

    return {
        "task_id": task.task_id,
        "status": "pending",
        "message": "大纲生成任务已提交，请通过 GET /generate/task/{task_id} 查询进度",
    }


@router.post("/{project_id}/structure/{structure_type}")
async def generate_structure(
    project_id: str,
    structure_type: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    tender_text = doc.parsed_content[:4000] if doc and doc.parsed_content else ""

    from services.generate.skills.structure_template_skill import StructureTemplateSkill

    gateway = get_llm_gateway()
    skill = StructureTemplateSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "structure_type": structure_type,
            "tender_text": tender_text,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
    }


@router.get("/{project_id}/score-coverage")
async def get_score_coverage(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    if not analysis or not analysis.scoring_matrix:
        raise HTTPException(status_code=400, detail="请先生成评分矩阵")

    outline_result = await db.execute(
        select(Outline).where(Outline.project_id == project.id)
    )
    outline = outline_result.scalar_one_or_none()
    outline_sections = []
    if outline and outline.tree:
        outline_sections = outline.tree if isinstance(outline.tree, list) else []

    from services.generate.skills.structure_template_skill import ScoreCoverageSkill

    gateway = get_llm_gateway()
    skill = ScoreCoverageSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "scoring_matrix": analysis.scoring_matrix,
            "outline_sections": outline_sections,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
    }


@router.post("/{project_id}/content/{chapter_id}")
async def generate_chapter(
    project_id: str,
    chapter_id: str,
    mode: str = "A",
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    tender_context = doc.parsed_content[:4000] if doc and doc.parsed_content else ""

    outline_result = await db.execute(
        select(Outline).where(Outline.project_id == project.id)
    )
    outline = outline_result.scalar_one_or_none()

    from services.generate.skills.content_gen_skill import ContentGenSkill

    gateway = get_llm_gateway()
    skill = ContentGenSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={
            "mode": mode,
            "chapter_title": chapter.title,
            "chapter_outline": json.dumps(outline.tree, ensure_ascii=False) if outline and outline.tree else "",
            "tender_context": tender_context,
            "word_count": 3000,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success and skill_result.data:
        chapter.content = skill_result.data.get("content", "")
        chapter.mode = mode
        chapter.status = "generated"
        chapter.word_count = skill_result.data.get("word_count", len(chapter.content))
        project.status = ProjectStatus.GENERATING
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.post("/{project_id}/content/stream/{chapter_id}")
async def stream_generate_chapter(
    project_id: str,
    chapter_id: str,
    mode: str = "A",
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    tender_context = doc.parsed_content[:4000] if doc and doc.parsed_content else ""

    outline_result = await db.execute(
        select(Outline).where(Outline.project_id == project.id)
    )
    outline = outline_result.scalar_one_or_none()

    gateway = get_llm_gateway()

    messages = [
        {
            "role": "system",
            "content": f'你是标书撰写专家。请撰写"{chapter.title}"章节。内容必须针对本项目，不得使用通用模板套话。',
        },
        {
            "role": "user",
            "content": f"招标要求上下文：\n{tender_context[:3000]}",
        },
    ]

    async def event_generator():
        collected_content = []
        try:
            async for chunk in gateway.stream_chat(messages=messages, temperature=0.5):
                collected_content.append(chunk)
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

            full_content = "".join(collected_content)
            chapter.content = full_content
            chapter.mode = mode
            chapter.status = "generated"
            chapter.word_count = len(full_content)
            await db.commit()

            yield f"data: {json.dumps({'done': True, 'word_count': len(full_content)}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{project_id}/mandatory-extract")
async def extract_mandatory_requirements(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
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

    from services.generate.skills.mandatory_req_extract_skill import MandatoryReqExtractSkill

    gateway = get_llm_gateway()
    skill = MandatoryReqExtractSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        parameters={"document_text": doc.parsed_content},
    )
    skill_result = await skill.safe_execute(ctx)

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }
