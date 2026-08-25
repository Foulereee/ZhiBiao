from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

import io

from docx import Document
from docx.shared import Pt, Cm, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fastapi import APIRouter, Body, Depends, HTTPException, Query
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


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    tm = TaskManager.instance()
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.to_dict()


async def _do_generate_outline(project_id: str, mode: str):
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

            structure_sections = []
            if project.config and isinstance(project.config, dict):
                saved_structure = project.config.get("structure_template")
                if saved_structure and isinstance(saved_structure, dict):
                    for _key, struct_val in saved_structure.items():
                        if isinstance(struct_val, dict) and "sections" in struct_val:
                            structure_sections.extend(struct_val["sections"])

            skill = OutlineGenSkill()
            ctx = SkillContext(
                project_id=project_id,
                db=db,
                llm=gateway,
                parameters={
                    "mode": mode,
                    "document_text": doc.parsed_content,
                    "scoring_matrix": scoring_matrix,
                    "structure_sections": structure_sections,
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
                    logger.warning(f"[大纲生成] 结果为空, skill_result.data keys={list(skill_result.data.keys()) if skill_result.data else 'None'}")
                    return {"success": False, "error": "大纲生成结果为空，可能是输出被截断。建议更换更大的模型或缩短招标文件后重试。"}

                existing = await db.execute(
                    select(Outline).where(Outline.project_id == project.id)
                )
                outline = existing.scalar_one_or_none()
                if outline:
                    outline.mode = mode
                    outline.tree = outline_data
                    outline.score_mapping = score_mapping
                    outline.reviewed = False
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

                from core.agent_engine.gate_keeper import GateKeeper
                gk = GateKeeper()
                gk.reset(project_id, "outline")
                gk.reset(project_id, "generate")

            result = {"success": skill_result.success}
            if skill_result.success:
                result["outline"] = outline_data
                result["mode"] = mode
            else:
                result["error"] = skill_result.error or "大纲生成失败"
            return result
        except Exception as e:
            logger.error(f"[大纲生成] 异常: {e}")
            return {"success": False, "error": str(e)}


@router.get("/{project_id}/outline")
async def get_outline(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    outline_result = await db.execute(
        select(Outline).where(Outline.project_id == project.id)
    )
    outline = outline_result.scalar_one_or_none()
    if not outline or not outline.tree:
        return {"success": True, "outline": None, "mode": None}

    return {
        "success": True,
        "outline": outline.tree,
        "mode": outline.mode,
        "score_mapping": outline.score_mapping,
        "reviewed": outline.reviewed,
        "updated_at": outline.updated_at.isoformat() if outline.updated_at else None,
    }


@router.post("/{project_id}/outline")
async def generate_outline(
    project_id: str,
    mode: str = "aligned",
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")

    tm = TaskManager.instance()
    task = await tm.submit("outline_gen", _do_generate_outline, project_id, mode)

    return {
        "task_id": task.task_id,
        "status": "pending",
        "message": "大纲生成任务已提交，请通过 GET /generate/task/{task_id} 查询进度",
    }


async def _do_generate_structure(project_id: str, structure_type: str):
    from services.database import async_session

    session_factory = async_session()
    async with session_factory() as db:
        try:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                return {"success": False, "error": "项目不存在"}

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

            if skill_result.success and skill_result.data:
                config = project.config or {}
                if not isinstance(config, dict):
                    config = {}
                existing = config.get("structure_template", {})
                if not isinstance(existing, dict):
                    existing = {}
                structures = skill_result.data.get("structures", {})
                existing.update(structures)
                config["structure_template"] = existing
                config["selected_structure_type"] = structure_type
                project.config = config
                await db.commit()

            return {
                "success": skill_result.success,
                "data": skill_result.data,
                "error": skill_result.error,
            }
        except Exception as e:
            logger.error(f"[结构模板生成] 异常: {e}")
            return {"success": False, "error": str(e)}


async def _do_score_coverage(project_id: str):
    from services.database import async_session

    session_factory = async_session()
    async with session_factory() as db:
        try:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                return {"success": False, "error": "项目不存在"}

            analysis_result = await db.execute(
                select(Analysis).where(Analysis.project_id == project.id)
            )
            analysis = analysis_result.scalar_one_or_none()
            if not analysis or not analysis.scoring_matrix:
                return {"success": False, "error": "请先生成评分矩阵"}

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
        except Exception as e:
            logger.error(f"[评分覆盖] 异常: {e}")
            return {"success": False, "error": str(e)}


async def _do_mandatory_extract(project_id: str):
    from services.database import async_session

    session_factory = async_session()
    async with session_factory() as db:
        try:
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
        except Exception as e:
            logger.error(f"[强制性要求提取] 异常: {e}")
            return {"success": False, "error": str(e)}


@router.post("/{project_id}/structure/{structure_type}")
async def generate_structure(
    project_id: str,
    structure_type: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")

    tm = TaskManager.instance()
    task = await tm.submit("structure_gen", _do_generate_structure, project_id, structure_type)

    return {
        "task_id": task.task_id,
        "status": "pending",
        "message": "结构模板生成任务已提交，请通过 GET /generate/task/{task_id} 查询进度",
    }


@router.post("/{project_id}/score-coverage")
async def get_score_coverage(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")

    tm = TaskManager.instance()
    task = await tm.submit("score_coverage", _do_score_coverage, project_id)

    return {
        "task_id": task.task_id,
        "status": "pending",
        "message": "评分覆盖率计算任务已提交，请通过 GET /generate/task/{task_id} 查询进度",
    }


@router.post("/{project_id}/mandatory-extract")
async def extract_mandatory_requirements(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")

    tm = TaskManager.instance()
    task = await tm.submit("mandatory_extract", _do_mandatory_extract, project_id)

    return {
        "task_id": task.task_id,
        "status": "pending",
        "message": "强制性要求提取任务已提交，请通过 GET /generate/task/{task_id} 查询进度",
    }


def _find_outline_node_with_context(
    chapters: list, node_id: str, parent: dict | None = None, siblings: list | None = None
) -> tuple[dict | None, dict | None, list]:
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        if ch.get("id") == node_id:
            return ch, parent, chapters
        children = ch.get("children", [])
        if children:
            found, found_parent, found_siblings = _find_outline_node_with_context(
                children, node_id, ch, children
            )
            if found:
                return found, found_parent, found_siblings
    return None, None, []


def _describe_node_tree(node: dict, indent: int = 0) -> str:
    prefix = "  " * indent
    title = node.get("title", "")
    lines = [f"{prefix}- {node.get('id', '')} {title}"]
    for child in node.get("children", []):
        if isinstance(child, dict):
            lines.append(_describe_node_tree(child, indent + 1))
    return "\n".join(lines)


def _build_chapter_context_text(
    chapter_node: dict | None,
    parent_node: dict | None,
    sibling_nodes: list,
    chapter_id: str,
) -> str:
    parts = []
    if chapter_node:
        children_desc = _describe_node_tree(chapter_node, indent=0)
        parts.append(f"【当前章节大纲】\n{children_desc}")
    if parent_node:
        parent_desc = f"{parent_node.get('id', '')} {parent_node.get('title', '')}"
        if parent_node.get("children"):
            parent_children = [
                f"  - {c.get('id', '')} {c.get('title', '')}"
                for c in parent_node.get("children", [])
                if isinstance(c, dict)
            ]
            parent_desc += "\n" + "\n".join(parent_children)
        parts.append(f"【上级章节】\n{parent_desc}")
    if sibling_nodes:
        sibling_lines = [
            f"- {s.get('id', '')} {s.get('title', '')}"
            for s in sibling_nodes
            if s.get("id") != chapter_id
        ]
        if sibling_lines:
            parts.append(f"【同级章节（请避免内容重复）】\n" + "\n".join(sibling_lines))
    return "\n\n".join(parts)


def _build_scoring_context(tree: dict, chapter_id: str, chapter_node: dict | None) -> str:
    if not tree.get("score_mapping"):
        return ""
    relevant_scores = {
        k: v for k, v in tree["score_mapping"].items()
        if v == chapter_id or (chapter_node and v == chapter_node.get("id", ""))
    }
    if not relevant_scores:
        return ""
    return "【相关评分项】\n" + "\n".join(
        f"- {name} → 章节{sid}" for name, sid in relevant_scores.items()
    )


def _extract_mandatory_requirements(analysis: Analysis | None) -> str:
    if not analysis or not analysis.dimensions:
        return ""
    dims = analysis.dimensions
    mandatory_items = []
    for key in ("mandatory", "mandatory_requirements", "必须响应", "强制性要求"):
        items = dims.get(key, [])
        if items and isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    desc = item.get("description", item.get("content", item.get("requirement", "")))
                    if desc:
                        mandatory_items.append(f"- {desc}")
                elif isinstance(item, str):
                    mandatory_items.append(f"- {item}")
    if not mandatory_items:
        risk_flags = dims.get("risk_flags", []) if isinstance(dims, dict) else []
        if risk_flags and isinstance(risk_flags, list):
            for flag in risk_flags:
                if isinstance(flag, dict):
                    desc = flag.get("description", flag.get("content", ""))
                    if desc:
                        mandatory_items.append(f"- [风险] {desc}")
    return "\n".join(mandatory_items)


def _extract_project_facts(analysis: Analysis | None) -> dict:
    if not analysis or not analysis.dimensions:
        return {}
    dims = analysis.dimensions
    facts = {}
    for key in ("project_info", "bidding_meta", "meta"):
        info = dims.get(key, {})
        if isinstance(info, dict):
            for k, v in info.items():
                if v and str(v).strip():
                    facts[k] = str(v)
    return facts


def _check_scoring_coverage_inline(tree: dict, contents: dict) -> dict | None:
    score_mapping = tree.get("score_mapping", {})
    if not score_mapping:
        return None

    full_text = "\n".join(contents.values())
    covered = 0
    missing_items = []

    for score_name, chapter_id in score_mapping.items():
        keywords = [w for w in re.split(r"[\s,，、]+", str(score_name)) if len(w) >= 2][:5]
        if any(kw in full_text for kw in keywords):
            covered += 1
        else:
            missing_items.append(score_name)

    total = len(score_mapping)
    if total == 0:
        return None

    return {
        "total": total,
        "covered": covered,
        "missing_count": len(missing_items),
        "coverage_rate": round(covered / total * 100, 1),
        "missing_items": missing_items[:10],
    }


def _get_knowledge_retriever():
    try:
        from services.routers.knowledge import _get_retriever
        return _get_retriever()
    except Exception:
        return None


class _KnowledgeBaseAdapter:
    def __init__(self, retriever, collection_name: str):
        self._retriever = retriever
        self._collection_name = collection_name

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        try:
            return await self._retriever.retrieve(
                query=query,
                collection_name=self._collection_name,
                top_k=top_k,
            )
        except Exception as e:
            logger.warning(f"知识库检索失败: {e}")
            return []


def _post_process_stream_content(content: str, chapter_title: str) -> str:
    from services.generate.skills.content_cleaner import clean_generated_content
    return clean_generated_content(content, chapter_title)


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

    chapter = None
    chapter_title = chapter_id
    chapter_node = None
    parent_node = None
    sibling_nodes = []

    if len(chapter_id) >= 32 and '-' in chapter_id:
        chapter_result = await db.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        chapter = chapter_result.scalar_one_or_none()
        if chapter:
            chapter_title = chapter.title

    outline_result = await db.execute(
        select(Outline).where(Outline.project_id == project.id)
    )
    outline = outline_result.scalar_one_or_none()
    tree = {}
    chapters_list = []
    if outline and outline.tree:
        tree = outline.tree if isinstance(outline.tree, dict) else {}
        chapters_list = tree.get("chapters", []) if isinstance(tree, dict) else []

    if not chapter and chapters_list:
        chapter_node, parent_node, sibling_nodes = _find_outline_node_with_context(
            chapters_list, chapter_id
        )
        if chapter_node:
            chapter_title = chapter_node.get("title", chapter_id)

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    tender_context = doc.parsed_content[:4000] if doc and doc.parsed_content else ""

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    mandatory_reqs = _extract_mandatory_requirements(analysis)

    chapter_context = _build_chapter_context_text(
        chapter_node, parent_node, sibling_nodes, chapter_id
    )
    scoring_context = _build_scoring_context(tree, chapter_id, chapter_node)

    chapter_outline = ""
    if chapter_node:
        chapter_outline = _describe_node_tree(chapter_node)
    elif outline and outline.tree:
        chapter_outline = json.dumps(outline.tree, ensure_ascii=False)

    knowledge_base = None
    if mode == "B":
        retriever = _get_knowledge_retriever()
        if retriever and outline and outline.tree:
            from services.routers.knowledge import _get_vector_store
            try:
                collections = _get_vector_store().client.list_collections()
                if collections:
                    knowledge_base = _KnowledgeBaseAdapter(retriever, collections[0].name)
            except Exception as e:
                logger.warning(f"知识库适配器创建失败: {e}")

    from services.generate.skills.content_gen_skill import ContentGenSkill

    gateway = get_llm_gateway()
    skill = ContentGenSkill()
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        knowledge_base=knowledge_base,
        parameters={
            "mode": mode,
            "chapter_title": chapter_title,
            "chapter_outline": chapter_outline[:2000],
            "chapter_context": chapter_context,
            "tender_context": tender_context,
            "scoring_context": scoring_context,
            "mandatory_requirements": mandatory_reqs,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success and skill_result.data:
        content = skill_result.data.get("content", "")
        if chapter:
            chapter.content = content
            chapter.mode = mode
            chapter.status = "generated"
            chapter.word_count = skill_result.data.get("word_count", len(content))
        project.status = ProjectStatus.GENERATING
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
        "warnings": skill_result.warnings,
    }


@router.get("/{project_id}/content/stream/{chapter_id}")
async def stream_generate_chapter(
    project_id: str,
    chapter_id: str,
    mode: str = "A",
):
    from services.database import async_session as _async_session
    db = _async_session()()
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    chapter = None
    chapter_title = chapter_id
    chapter_node = None
    parent_node = None
    sibling_nodes = []

    if len(chapter_id) >= 32 and '-' in chapter_id:
        chapter_result = await db.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        chapter = chapter_result.scalar_one_or_none()
        if chapter:
            chapter_title = chapter.title

    outline_result = await db.execute(
        select(Outline).where(Outline.project_id == project.id)
    )
    outline = outline_result.scalar_one_or_none()
    tree = {}
    chapters_list = []
    if outline and outline.tree:
        tree = outline.tree if isinstance(outline.tree, dict) else {}
        chapters_list = tree.get("chapters", []) if isinstance(tree, dict) else []

    if not chapter and chapters_list:
        chapter_node, parent_node, sibling_nodes = _find_outline_node_with_context(
            chapters_list, chapter_id
        )
        if chapter_node:
            chapter_title = chapter_node.get("title", chapter_id)

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    tender_context = doc.parsed_content[:4000] if doc and doc.parsed_content else ""

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    mandatory_reqs = _extract_mandatory_requirements(analysis)

    chapter_context = _build_chapter_context_text(
        chapter_node, parent_node, sibling_nodes, chapter_id
    )
    scoring_context = _build_scoring_context(tree, chapter_id, chapter_node)

    from services.generate.skills.content_gen_skill import ContentGenSkill
    word_count = ContentGenSkill._infer_word_count(chapter_title)

    system_prompt = f"""你是具有十年以上经验的资深投标文件撰写专家。请撰写\u201c{chapter_title}\u201d章节。

【撰写规范】
1. 结构要求：
   - 本章必须包含至少 3 个二级节（用 ### 标记）
   - 每个二级节下必须包含至少 2-3 个三级小节（用 #### 标记）
   - 每个三级小节正文不少于 500 字，重要小节应达到 800-1000 字
   - 可适当使用表格展示对比、清单、计划等结构化信息

2. 语言风格：
   - 使用正式、严谨、专业的投标文件语言
   - 使用\u201c本公司\u201d、\u201c投标人\u201d指代己方，\u201c采购人\u201d、\u201c招标人\u201d指代对方
   - 禁止口语化表达、禁止\u201c我们\u201d、\u201c你们\u201d
   - 禁止模糊表述如\u201c如有需要\u201d、\u201c可以考虑\u201d、\u201c大概\u201d

3. 内容要求：
   - 每个要点必须展开论述，给出具体措施、方法、流程或标准
   - 技术方案章节应包含：总体设计思路、技术架构、关键技术、实施方案、质量保障
   - 服务方案章节应包含：服务体系、服务内容、服务流程、服务标准、应急预案
   - 管理方案章节应包含：组织架构、管理制度、人员配置、培训计划、考核机制

4. 禁止事项：
   - 不得编造企业名称、资质证书、项目案例、人员信息、合同金额
   - 不得使用代码块包裹正文
   - 表格内不得出现 Markdown 格式标记

5. 篇幅要求：
   - 每个三级小节正文不少于 500 字
   - 本章节总字数不少于 {word_count} 字

6. 输出格式：
   - 直接输出章节正文（从 ### 二级节标题开始）
   - 不要输出章节一级标题
   - 不要输出任何解释、说明或总结

7. 质量要求（极其重要）：
   - 每个字词只能出现一次，绝对禁止重复（如\u201c采用采用\u201d\u201c包括包括\u201d\u201c项目项目\u201d）
   - 禁止输出任何无意义的单字母（如\u201cz\u201d\u201cx\u201d等）
   - 禁止输出乱码或不可读字符
   - 标题编号必须规范（如 ### 1.1、#### 1.1.1），禁止出现\u201c1####\u201d\u201cd D.\u201d等格式
   - 每个标点符号只用一次，禁止重复（如\u201c。。。。\u201d）
   - 输出前请逐字检查，确保无重复词、无错字、无乱码"""

    messages = [{"role": "system", "content": system_prompt}]

    if tender_context:
        messages.append({
            "role": "user",
            "content": f"【招标要求上下文】\n{tender_context[:3000]}",
        })

    if chapter_context:
        messages.append({
            "role": "user",
            "content": chapter_context,
        })

    if scoring_context:
        messages.append({
            "role": "user",
            "content": scoring_context,
        })

    if mandatory_reqs:
        messages.append({
            "role": "user",
            "content": f"【必须响应的强制性要求】\n{mandatory_reqs[:2000]}",
        })

    chapter_outline = ""
    if chapter_node:
        chapter_outline = _describe_node_tree(chapter_node)
    if chapter_outline:
        messages.append({
            "role": "user",
            "content": f"【章节大纲】\n{chapter_outline[:2000]}",
        })

    rag_context = ""
    if mode == "B":
        retriever = _get_knowledge_retriever()
        if retriever:
            try:
                from services.routers.knowledge import _get_vector_store
                collections = _get_vector_store().client.list_collections()
                if collections:
                    collection_name = collections[0].name
                    query = f"{chapter_title} {chapter_outline[:200]}"
                    rag_results = await retriever.retrieve(
                        query=query,
                        collection_name=collection_name,
                        top_k=5,
                    )
                    if rag_results:
                        rag_context = "\n\n".join(
                            f"<knowledge_content>\n{r.get('text', r.get('content', ''))[:800]}\n</knowledge_content>"
                            for r in rag_results
                        )
            except Exception as e:
                logger.warning(f"流式生成RAG检索失败: {e}")

    if rag_context:
        messages.append({
            "role": "user",
            "content": f"【参考材料（请优先引用其中的具体数据和案例）】\n{rag_context[:6000]}",
        })

    messages.append({
        "role": "user",
        "content": f'请撰写\u201c{chapter_title}\u201d章节的完整正文。',
    })

    gateway = get_llm_gateway()

    outline_id = outline.id if outline else None

    async def event_generator():
        collected_content = []
        try:
            async for chunk in gateway.stream_chat(messages=messages, temperature=0.7):
                collected_content.append(chunk)
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

            full_content = "".join(collected_content)
            full_content = _post_process_stream_content(full_content, chapter_title)

            # Create a DB session for persistence ( the generator outlives the DI session)
            from services.database import async_session
            session_factory = async_session()
            async with session_factory() as persist_db:
                is_uuid = bool(chapter_id) and len(chapter_id) >= 32 and '-' in chapter_id
                chapter_record = None
                if is_uuid:
                    ch_result = await persist_db.execute(
                        select(Chapter).where(Chapter.id == chapter_id)
                    )
                    chapter_record = ch_result.scalar_one_or_none()

                if chapter_record is None and outline_id and chapter_title:
                    lookup_conditions = [
                        Chapter.project_id == project_id,
                        Chapter.outline_id == outline_id,
                        Chapter.title == chapter_title,
                    ]
                    lookup_result = await persist_db.execute(
                        select(Chapter).where(*lookup_conditions)
                    )
                    chapter_record = lookup_result.scalar_one_or_none()

                if chapter_record is not None:
                    chapter_record.content = full_content
                    chapter_record.mode = mode
                    chapter_record.status = "generated"
                    chapter_record.word_count = len(full_content)
                elif outline_id and chapter_title:
                    new_ch = Chapter(
                        project_id=project_id,
                        outline_id=outline_id,
                        title=chapter_title,
                        content=full_content,
                        mode=mode,
                        status="generated",
                        word_count=len(full_content),
                    )
                    persist_db.add(new_ch)

                project_result = await persist_db.execute(
                    select(Project).where(Project.id == project_id)
                )
                project_record = project_result.scalar_one_or_none()
                if project_record:
                    project_record.status = ProjectStatus.GENERATING
                await persist_db.commit()

            yield f"data: {json.dumps({'done': True, 'word_count': len(full_content)}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"[流式生成] 异常: {e}")
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _collect_chapter_ids(nodes: list, parent: dict | None = None) -> list[dict]:
    results = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        entry = {
            "id": node.get("id", ""),
            "title": node.get("title", ""),
            "parent_id": parent.get("id", "") if parent else "",
            "parent_title": parent.get("title", "") if parent else "",
        }
        results.append(entry)
        children = node.get("children", [])
        if children:
            results.extend(_collect_chapter_ids(children, node))
    return results


def _find_chapter_title_by_id(nodes: list, target_id: str) -> str:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("id") == target_id:
            return node.get("title", "")
        children = node.get("children", [])
        if children:
            found = _find_chapter_title_by_id(children, target_id)
            if found:
                return found
    return ""


@router.get("/{project_id}/content/stream-all")
async def stream_generate_all_chapters(
    project_id: str,
    mode: str = "A",
):
    from services.database import async_session as _async_session
    db = _async_session()()
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    outline_result = await db.execute(
        select(Outline).where(Outline.project_id == project.id)
    )
    outline = outline_result.scalar_one_or_none()
    if not outline or not outline.tree:
        raise HTTPException(status_code=400, detail="请先生成大纲")

    tree = outline.tree if isinstance(outline.tree, dict) else {}
    chapters_list = tree.get("chapters", []) if isinstance(tree, dict) else []
    if not chapters_list:
        raise HTTPException(status_code=400, detail="大纲章节为空")

    all_chapters = _collect_chapter_ids(chapters_list)
    if not all_chapters:
        raise HTTPException(status_code=400, detail="大纲中无有效章节")

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    tender_context = doc.parsed_content[:4000] if doc and doc.parsed_content else ""

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    mandatory_reqs = _extract_mandatory_requirements(analysis)

    gateway = get_llm_gateway()

    async def batch_event_generator():
        total = len(all_chapters)
        completed = 0
        failed = 0
        all_contents: dict[str, str] = {}

        yield f"data: {json.dumps({'type': 'start', 'total': total}, ensure_ascii=False)}\n\n"

        # --- Concurrent generation (Semaphore=4) ---
        semaphore = asyncio.Semaphore(4)
        gen_tasks = []

        async def _gen_one(ch_info):
            ch_id = ch_info["id"]
            ch_title = ch_info["title"]
            async with semaphore:
                try:
                    chapter_node, parent_node, sibling_nodes = _find_outline_node_with_context(
                        chapters_list, ch_id
                    )
                    chapter_context = _build_chapter_context_text(
                        chapter_node, parent_node, sibling_nodes, ch_id
                    )
                    scoring_context = _build_scoring_context(tree, ch_id, chapter_node)
                    chapter_outline = ""
                    if chapter_node:
                        chapter_outline = _describe_node_tree(chapter_node)

                    from services.generate.skills.content_gen_skill import ContentGenSkill
                    wc = ContentGenSkill._infer_word_count(ch_title)

                    system_prompt = f"""你是具有十年以上经验的资深投标文件撰写专家。请撰写“{ch_title}”章节。

【撰写规范】
1. 结构要求：
   - 本章必须包含至少 3 个二级节（用 ### 标记）
   - 每个二级节下必须包含至少 2-3 个三级小节（用 #### 标记）
   - 每个三级小节正文不少于 500 字，重要小节应达到 800-1000 字
   - 可适当使用表格展示对比、清单、计划等结构化信息

2. 语言风格：
   - 使用正式、严谨、专业的投标文件语言
   - 使用“本公司”、“投标人”指代己方，“采购人”、“招标人”指代对方
   - 禁止口语化表达、禁止“我们”、“你们”
   - 禁止模糊表述如“如有需要”、“可以考虑”、“大概”

3. 内容要求：
   - 每个要点必须展开论述，给出具体措施、方法、流程或标准
   - 技术方案章节应包含：总体设计思路、技术架构、关键技术、实施方案、质量保障
   - 服务方案章节应包含：服务体系、服务内容、服务流程、服务标准、应急预案
   - 管理方案章节应包含：组织架构、管理制度、人员配置、培训计划、考核机制

4. 禁止事项：
   - 不得编造企业名称、资质证书、项目案例、人员信息、合同金额
   - 不得使用代码块包裹正文
   - 表格内不得出现 Markdown 格式标记

5. 篇幅要求：
   - 每个三级小节正文不少于 500 字
   - 本章节总字数不少于 {wc} 字

6. 输出格式：
   - 直接输出章节正文（从 ### 二级节标题开始）
   - 不要输出章节一级标题
   - 不要输出任何解释、说明或总结

7. 质量要求（极其重要）：
   - 每个字词只能出现一次，绝对禁止重复（如“采用采用”“包括包括”“项目项目”）
   - 禁止输出任何无意义的单字母（如“z”“x”等）
   - 禁止输出乱码或不可读字符
   - 标题编号必须规范（如 ### 1.1、#### 1.1.1），禁止出现“1####”“d D.”等格式
   - 每个标点符号只用一次，禁止重复（如“。。。。”）
   - 输出前请逐字检查，确保无重复词、无错字、无乱码"""

                    msgs = [{"role": "system", "content": system_prompt}]
                    if tender_context:
                        msgs.append({"role": "user", "content": f"【招标要求上下文】\n{tender_context[:3000]}"})
                    if chapter_context:
                        msgs.append({"role": "user", "content": chapter_context})
                    if scoring_context:
                        msgs.append({"role": "user", "content": scoring_context})
                    if mandatory_reqs:
                        msgs.append({"role": "user", "content": f"【必须响应的强制性要求】\n{mandatory_reqs[:2000]}"})
                    if chapter_outline:
                        msgs.append({"role": "user", "content": f"【章节大纲】\n{chapter_outline[:2000]}"})

                    if mode == "B":
                        retriever = _get_knowledge_retriever()
                        if retriever:
                            try:
                                from services.routers.knowledge import _get_vector_store
                                collections = _get_vector_store().client.list_collections()
                                if collections:
                                    cn = collections[0].name
                                    q = f"{ch_title} {chapter_outline[:200]}"
                                    rag_res = await retriever.retrieve(query=q, collection_name=cn, top_k=5)
                                    if rag_res:
                                        rc = "\n\n".join(
                                            f"<knowledge_content>\n{r.get('text', r.get('content', ''))[:800]}\n</knowledge_content>"
                                            for r in rag_res
                                        )
                                        msgs.append({"role": "user", "content": f"【参考材料（请优先引用其中的具体数据和案例）】\n{rc[:6000]}"})
                            except Exception as e:
                                logger.warning(f"批量生成RAG检索失败(chapter={ch_id}): {e}")

                    msgs.append({"role": "user", "content": f'请撰写“{ch_title}”章节的完整正文。'})

                    collected = []
                    async for chunk in gateway.stream_chat(messages=msgs, temperature=0.7):
                        collected.append(chunk)
                    full_content = "".join(collected)
                    full_content = _post_process_stream_content(full_content, ch_title)
                    return ("ok", ch_id, ch_title, full_content)
                except Exception as e:
                    return ("error", ch_id, ch_title, str(e))

        for ch_info in all_chapters:
            gen_tasks.append(asyncio.create_task(_gen_one(ch_info)))

        for task in asyncio.as_completed(gen_tasks):
            result = await task
            if result[0] == "ok":
                _, ch_id, ch_title, full_content = result
                all_contents[ch_id] = full_content
                completed += 1
                yield f"data: {json.dumps({'type': 'chapter_done', 'chapter_id': ch_id, 'chapter_title': ch_title, 'word_count': len(full_content), 'completed': completed, 'total': total}, ensure_ascii=False)}\n\n"
            else:
                _, ch_id, ch_title, err_msg = result
                failed += 1
                logger.error(f"[批量生成] 章节{ch_id}({ch_title})失败: {err_msg}")
                yield f"data: {json.dumps({'type': 'chapter_error', 'chapter_id': ch_id, 'chapter_title': ch_title, 'error': str(err_msg)[:200]}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'post_check', 'message': '正在进行生成后检查...'}, ensure_ascii=False)}\n\n"

        try:
            full_bid_text = "\n\n".join(all_contents.values())
            project_facts = _extract_project_facts(analysis)

            from services.check.skills.consistency_check_skill import ConsistencyCheckSkill
            consistency_skill = ConsistencyCheckSkill()
            consistency_ctx = SkillContext(
                project_id=project_id,
                db=None,
                llm=gateway,
                parameters={
                    "bid_text": full_bid_text[:8000],
                    "tender_context": tender_context,
                    "project_facts": project_facts,
                },
            )
            consistency_result = await consistency_skill.safe_execute(consistency_ctx)
            if consistency_result.success:
                yield f"data: {json.dumps({'type': 'consistency_check', 'data': consistency_result.data}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.warning(f"[批量生成] 一致性检查失败: {e}")

        try:
            scoring_report = _check_scoring_coverage_inline(tree, all_contents)
            if scoring_report:
                yield f"data: {json.dumps({'type': 'scoring_coverage', 'data': scoring_report}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.warning(f"[批量生成] 评分覆盖检查失败: {e}")

        try:
            from services.database import async_session
            session_factory = async_session()
            async with session_factory() as persist_db:
                proj_result = await persist_db.execute(
                    select(Project).where(Project.id == project_id)
                )
                proj_record = proj_result.scalar_one_or_none()

                for ch_id, ch_content in all_contents.items():
                    ch_title = _find_chapter_title_by_id(chapters_list, ch_id)
                    conditions = [
                        Chapter.project_id == proj_record.id,
                        Chapter.title == ch_title,
                    ]
                    if outline:
                        conditions.append(Chapter.outline_id == outline.id)
                    existing_ch = await persist_db.execute(
                        select(Chapter).where(*conditions)
                    )
                    ch_record = existing_ch.scalar_one_or_none()
                    if ch_record:
                        ch_record.content = ch_content
                        ch_record.status = "generated"
                        ch_record.word_count = len(ch_content)
                    else:
                        new_ch = Chapter(
                            project_id=proj_record.id,
                            outline_id=outline.id if outline else None,
                            title=ch_title or ch_id,
                            content=ch_content,
                            mode=mode,
                            status="generated",
                            word_count=len(ch_content),
                        )
                        persist_db.add(new_ch)
                if proj_record:
                    proj_record.status = ProjectStatus.GENERATING
                await persist_db.commit()
        except Exception as e:
            logger.warning(f"[批量生成] 内容持久化失败: {e}")

        yield f"data: {json.dumps({'type': 'done', 'total': total, 'completed': completed, 'failed': failed}, ensure_ascii=False)}\n\n"

    return StreamingResponse(batch_event_generator(), media_type="text/event-stream")


@router.get("/{project_id}/chapters")
async def list_chapters(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    ch_result = await db.execute(
        select(Chapter).where(Chapter.project_id == project.id).order_by(Chapter.sort_order)
    )
    chapters = ch_result.scalars().all()

    return {
        "success": True,
        "chapters": [
            {
                "id": ch.id,
                "title": ch.title,
                "content": ch.content or "",
                "mode": ch.mode,
                "status": ch.status,
                "word_count": ch.word_count,
                "has_content": bool(ch.content and ch.content.strip()),
                "updated_at": ch.updated_at.isoformat() if ch.updated_at else None,
            }
            for ch in chapters
        ],
    }


@router.get("/{project_id}/chapters/{chapter_id}")
async def get_chapter_content(
    project_id: str,
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    ch_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id, Chapter.project_id == project.id)
    )
    chapter = ch_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    return {
        "success": True,
        "chapter": {
            "id": chapter.id,
            "title": chapter.title,
            "content": chapter.content or "",
            "mode": chapter.mode,
            "status": chapter.status,
            "word_count": chapter.word_count,
        },
    }


@router.put("/{project_id}/chapters/{chapter_id}")
async def update_chapter_content(
    project_id: str,
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
    content: str = Body("", embed=True),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    ch_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id, Chapter.project_id == project.id)
    )
    chapter = ch_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    chapter.content = content
    chapter.word_count = len(content)
    chapter.status = "edited"
    await db.commit()

    return {
        "success": True,
        "chapter": {
            "id": chapter.id,
            "title": chapter.title,
            "content": chapter.content,
            "word_count": chapter.word_count,
            "status": chapter.status,
        },
    }


def _parse_markdown_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        rows.append(cells)
    return rows


def _add_table_to_doc(doc: Document, rows: list[list[str]]):
    if not rows:
        return
    num_cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=num_cols)
    table.style = "Table Grid"
    for i, row_data in enumerate(rows):
        for j, cell_text in enumerate(row_data):
            if j < num_cols:
                cell = table.rows[i].cells[j]
                cell.text = cell_text
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.first_line_indent = Pt(0)
                    for run in paragraph.runs:
                        run.font.name = "宋体"
                        run.font.size = Pt(10.5)


def _add_markdown_to_doc(doc: Document, md_text: str):
    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("# ") and not line.startswith("## "):
            heading_text = line.lstrip("#").strip()
            heading = doc.add_heading(heading_text, level=1)
            for run in heading.runs:
                run.font.name = "宋体"
            i += 1
            continue

        if line.startswith("## ") and not line.startswith("### "):
            heading_text = line.lstrip("#").strip()
            heading = doc.add_heading(heading_text, level=1)
            for run in heading.runs:
                run.font.name = "宋体"
            i += 1
            continue

        if line.startswith("### ") and not line.startswith("#### "):
            heading_text = line.lstrip("#").strip()
            heading = doc.add_heading(heading_text, level=2)
            for run in heading.runs:
                run.font.name = "宋体"
            i += 1
            continue

        if line.startswith("#### "):
            heading_text = line.lstrip("#").strip()
            heading = doc.add_heading(heading_text, level=3)
            for run in heading.runs:
                run.font.name = "宋体"
            i += 1
            continue

        if line.strip().startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            rows = _parse_markdown_table(table_lines)
            _add_table_to_doc(doc, rows)
            continue

        if line.strip():
            para = doc.add_paragraph()
            para.paragraph_format.line_spacing = 1.5
            para.paragraph_format.first_line_indent = Pt(24)
            run = para.add_run(line.strip())
            run.font.name = "宋体"
            run.font.size = Pt(12)

        i += 1


@router.get("/{project_id}/export-docx")
async def export_docx(
    project_id: str,
    fmt: str = Query("docx", pattern="^(docx|doc|pdf)$"),
    template: str = Query("default"),
    apply_format: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    ch_result = await db.execute(
        select(Chapter).where(Chapter.project_id == project.id).order_by(Chapter.sort_order)
    )
    chapters = ch_result.scalars().all()

    if not chapters:
        raise HTTPException(status_code=400, detail="暂无已生成的章节内容")

    doc = Document()

    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.17)
    section.right_margin = Cm(3.17)

    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_para.paragraph_format.space_before = Pt(72)
    title_para.paragraph_format.space_after = Pt(36)
    title_run = title_para.add_run(project.name)
    title_run.font.name = "宋体"
    title_run.font.size = Pt(22)
    title_run.bold = True

    doc.add_page_break()

    for chapter in chapters:
        if chapter.title:
            heading = doc.add_heading(chapter.title, level=1)
            for run in heading.runs:
                run.font.name = "宋体"

        if chapter.content:
            _add_markdown_to_doc(doc, chapter.content)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    export_root = Path("./uploads/exports")
    export_root.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", project.name)[:80] or "project"
    base_path = export_root / f"{safe_name}_{int(time.time())}"
    docx_path = base_path.with_suffix(".docx")
    docx_path.write_bytes(buffer.getvalue())

    try:
        if apply_format and template and template != "none":
            from services.format.skills.docx_format_skill import DocxFormatSkill
            fmt_skill = DocxFormatSkill()
            ctx = SkillContext(
                project_id=project.id,
                db=db,
                llm=get_llm_gateway(),
                parameters={
                    "file_path": str(docx_path),
                    "template": template,
                    "mode": "format",
                },
            )
            fmt_result = await fmt_skill.safe_execute(ctx)
            if fmt_result.success and fmt_result.data and fmt_result.data.get("output_path"):
                new_path = Path(fmt_result.data["output_path"])
                if new_path.exists() and new_path != docx_path:
                    docx_path.unlink(missing_ok=True)
                    docx_path = new_path

        if fmt == "docx":
            data = docx_path.read_bytes()
            return StreamingResponse(
                io.BytesIO(data),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}.docx"},
            )

        if fmt == "pdf":
            from services.format.skills.pdf_export_skill import PdfExportSkill
            pdf_skill = PdfExportSkill()
            ctx = SkillContext(
                project_id=project.id,
                db=db,
                llm=get_llm_gateway(),
                parameters={
                    "input_path": str(docx_path),
                    "output_dir": str(export_root),
                },
            )
            pdf_result = await pdf_skill.safe_execute(ctx)
            if not pdf_result.success or not pdf_result.data:
                raise HTTPException(status_code=500, detail=pdf_result.error or "PDF 转换失败")
            pdf_path = Path(pdf_result.data["output_path"])
            data = pdf_path.read_bytes()
            try:
                pdf_path.unlink(missing_ok=True)
                docx_path.unlink(missing_ok=True)
            except OSError:
                pass
            return StreamingResponse(
                io.BytesIO(data),
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}.pdf"},
            )

        if fmt == "doc":
            from services.format.skills.doc_export_skill import DocExportSkill
            doc_skill = DocExportSkill()
            doc_result = doc_skill._try_libreoffice_doc(docx_path, export_root)
            if not doc_result.get("success"):
                raise HTTPException(status_code=500, detail=doc_result.get("error", "doc 转换失败"))
            doc_path = Path(doc_result["output_path"])
            data = doc_path.read_bytes()
            try:
                doc_path.unlink(missing_ok=True)
                docx_path.unlink(missing_ok=True)
            except OSError:
                pass
            return StreamingResponse(
                io.BytesIO(data),
                media_type="application/msword",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}.doc"},
            )
    except HTTPException:
        try:
            docx_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception as e:
        logger.exception("export-docx 后处理失败")
        try:
            docx_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")
