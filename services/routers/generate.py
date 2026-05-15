from __future__ import annotations

import uuid
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import Project, Document, Analysis, Outline, Chapter, ProjectStatus
from services.llm_factory import get_llm_gateway
from core.skill_engine.base import SkillContext

router = APIRouter()


@router.post("/{project_id}/outline")
async def generate_outline(
    project_id: str,
    mode: str = "aligned",
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc or not doc.parsed_content:
        raise HTTPException(status_code=400, detail="请先解析招标文件")

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()

    scoring_matrix = {}
    if analysis and analysis.scoring_matrix:
        scoring_matrix = analysis.scoring_matrix

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
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        outline_data = skill_result.data.get("outline", {})
        score_mapping = skill_result.data.get("score_mapping", {})

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

        project.status = ProjectStatus.OUTLINING
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.post("/{project_id}/structure/{structure_type}")
async def generate_structure(
    project_id: str,
    structure_type: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
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
    result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
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
    result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == uuid.UUID(chapter_id))
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
    result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == uuid.UUID(chapter_id))
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
    result = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
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
