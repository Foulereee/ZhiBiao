from __future__ import annotations

import asyncio
import os
import json
import logging
import re
import time
from pathlib import Path

import io

from docx import Document as DocxDocument
from docx.shared import Pt, Cm, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
# 注意: 下一行的数据库模型 Document 与 python-docx 的 Document 同名,
# 会覆盖上面的导入。python-docx 的已别名为 DocxDocument。
# 曾因此导致导出 Word 报 'Document' object has no attribute 'sections'。
from services.models import Project, Document, Analysis, Outline, Chapter, ProjectStatus, iso_utc
from services.llm_factory import get_llm_gateway
from core.skill_engine.base import SkillContext
from core.task_manager import TaskManager

logger = logging.getLogger(__name__)
from services.middleware.api_key import require_any_auth

router = APIRouter(dependencies=[Depends(require_any_auth)])

# 用户实测:导出的 docx 每页约 800 字,页数估算统一按这个口径
CHARS_PER_PAGE = 800
# 单章目标字数的安全区间,避免用户把总字数设得过小时每章只剩一两句话。
# 下限从 300 → 150 → 120:上限其实由篇幅反解公式(BMP_LEN_SLOPE 那段)决定,
# 这个下限只是防呆。设成 150 时,目标 8 万字反解出的 130 字预算会被顶回去,
# 最终固定落在 121 页,公式等于失效;降到 120 后 8 万字目标能落在 ~100 页。
MIN_CHAPTER_WORDS = 120
MAX_CHAPTER_WORDS = 5000
# 有下级章节的分支节点只写这么长的"本章概述"(见 build_chapter_system_prompt)
OVERVIEW_WORDS = 220

# 导出时要在正文后附"此处需插入图片"1×1 灰字表格的章节标题特征。
# 比 content_gen_skill 的 _DATA_DEPENDENT_KEYWORDS 窄:那里把"业绩/合同/人员配置"
# 也算数据依赖,但那些是要写文字而不是贴图,附表格反而干扰阅读。
_IMAGE_CHAPTER_PAT = re.compile(
    r"营业执照|银行保函|保函|开户许可|保证金.{0,6}(凭证|回单|交纳|依据|到账)|"
    r"回单|凭证|复印件|扫描件|身份证明|授权委托|资质证书|社保|纳税|"
    r"审计报告|财务报告|公章|印章"
)


def resolve_chapter_words(
    explicit_words: int = 0,
    title: str = "",
    total_words: int = 0,
    chapter_count: int = 0,
) -> int:
    """决定"本章目标字数"。

    优先级:全书总字数均摊 > 明确的单章字数 > 按标题推断(旧行为)。
    用户反馈过"300 章生成 87.9 万字",根因就是以前只能按标题推断(默认 2500,
    技术类 4000),逐章相加完全没有总量概念。
    """
    if total_words and chapter_count:
        return max(MIN_CHAPTER_WORDS, min(MAX_CHAPTER_WORDS, round(total_words / chapter_count)))
    if explicit_words and explicit_words > 0:
        return max(MIN_CHAPTER_WORDS, min(MAX_CHAPTER_WORDS, int(explicit_words)))
    from services.generate.skills.content_gen_skill import ContentGenSkill
    return ContentGenSkill._infer_word_count(title)


def _fallback_overview(title: str) -> str:
    """模型彻底失败时的显式占位,不再伪造正文。

    以前这里返回"本章围绕…作总体说明。本公司将按招标文件要求…"这种通篇一模一样的
    套话,结果 181/303 章(60%)都成了同一段文字,整份标书看起来就是模板。
    根因是推理模型把 token 全烧在思考上(finish_reason=length,正文 0 字),
    已在网关侧用 thinking={"type":"disabled"} 修掉。
    真到了这一步就写一句能一眼看出的提示,方便定位并单章重新生成,绝不编造正文。
    """
    return f"【本章正文未能生成】模型未返回内容。请在「投标生成」页对「{title}」重新生成本章。"


def build_chapter_system_prompt(title: str, words: int, overview: bool = False) -> str:
    """构造单章正文的系统提示词(流式单章与批量生成共用一份)。

    关于字数:以前写的是"本章节总字数不少于 {wc} 字",而且硬性要求
    "每个三级小节不少于 500 字"。下限式约束只会让模型越写越长(实际每章
    ~2900 字),现在改成"控制在 X 字左右"并让子节数量随目标字数伸缩。

    overview=True 用于"有下级章节的分支节点":只写一段本章概述,不输出
    ###/#### 小标题。以前分支节点也按整棵子树生成,同一批编号在文档里
    重复出现(实测 1718 条带编号标题只有 1506 个不同值)。
    """
    if overview:
        return f"""你是具有十年以上经验的资深投标文件撰写专家。请为“{title}”这一章撰写本章概述。

【要求】
1. 只写一段本章概述,{MIN_CHAPTER_WORDS}-{max(MIN_CHAPTER_WORDS + 200, words)} 字,说明本章要解决什么问题、包含哪些下级内容。
2. 【严禁】输出任何 ### 或 #### 小标题(下级内容由各自的章节展开,不要在本章重复)。
3. 【严禁】重复下级章节的内容,不要罗列细节措施。
4. 使用正式、严谨的投标文件语言,用“本公司”“投标人”指代己方。
5. 不得编造企业名称、资质证书、项目案例、人员信息、合同金额。
6. 直接输出概述正文,不要输出章节标题,不要输出任何解释或说明。"""

    lo = max(MIN_CHAPTER_WORDS, int(words * 0.8))
    hi = int(words * 1.25)
    # 目标字数小的时候不能还要求 3 个二级节 × 2-3 个三级节,否则必然超写
    if words <= 800:
        structure_rule = (
            "   - 本章篇幅较小,写 1-2 个二级节（用 ### 标记）即可,"
            "每个二级节下 1-2 个三级小节（用 #### 标记),不要为了凑小节数量重复内容\n"
        )
    elif words <= 1800:
        structure_rule = (
            "   - 本章写 2-3 个二级节（用 ### 标记）,每个二级节下 2 个左右三级小节（用 #### 标记）\n"
        )
    else:
        structure_rule = (
            "   - 本章必须包含至少 3 个二级节（用 ### 标记）\n"
            "   - 每个二级节下必须包含至少 2-3 个三级小节（用 #### 标记）\n"
        )
    return f"""你是具有十年以上经验的资深投标文件撰写专家。请撰写“{title}”章节。

【撰写规范】
1. 结构要求：
{structure_rule}   - 可适当使用表格展示对比、清单、计划等结构化信息

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

5. 篇幅要求（重要）：
   - 本章节总字数控制在 {words} 字左右，合理范围 {lo}-{hi} 字
   - 【重要】不得少于 {lo} 字。去掉下限后模型会明显少写(实测目标 12 万字只写出 7.2 万字)
   - 【严禁】为了凑字数而重复相同句子、重复段落或堆砌同义排比
   - 写完目标字数即可收尾，超出 {hi} 字视为不合格

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
        "updated_at": iso_utc(outline.updated_at),
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
            if not analysis:
                return {"success": False, "error": "请先完成招标解读,再运行评分覆盖检查"}

            # 评分矩阵可能缺失或为空(解读阶段没提取到评分项):用招标文件原文现场重构一次,
            # 而不是直接抛"评分矩阵中无评分项"让用户看不懂
            matrix = analysis.scoring_matrix if isinstance(analysis.scoring_matrix, dict) else {}
            rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
            if not rows:
                from services.interpret.skills.scoring_matrix_skill import ScoringMatrixSkill
                from services.models import Document as _DocModel

                doc_result = await db.execute(
                    select(_DocModel)
                    .where(_DocModel.project_id == project.id)
                    .order_by(_DocModel.created_at.asc())
                )
                doc = doc_result.scalars().first()
                doc_text = (getattr(doc, "parsed_content", "") or "") if doc else ""
                rebuild_ctx = SkillContext(
                    project_id=project_id,
                    db=db,
                    llm=get_llm_gateway(),
                    parameters={
                        "scoring_data": (analysis.dimensions or {}).get("scoring", {})
                        if analysis.dimensions
                        else {},
                        "document_text": doc_text,
                    },
                )
                rebuild = await ScoringMatrixSkill().safe_execute(rebuild_ctx)
                new_rows = (
                    rebuild.data.get("rows") or []
                    if rebuild.success and isinstance(rebuild.data, dict)
                    else []
                )
                if not new_rows:
                    return {
                        "success": False,
                        "data": rebuild.data,
                        "error": rebuild.error or "该项目没有识别到评分项,无法做评分覆盖检查。",
                    }
                analysis.scoring_matrix = rebuild.data
                await db.flush()
                await db.commit()
                matrix = rebuild.data
                logger.info(f"[评分覆盖] 为项目 {project_id} 现场重构评分矩阵,共 {len(new_rows)} 项")

            outline_result = await db.execute(
                select(Outline).where(Outline.project_id == project.id)
            )
            outline = outline_result.scalar_one_or_none()
            # outlines.tree 存的是 {"chapters": [...], "score_mapping": {...}} 这个 dict，
            # 旧代码写的是 isinstance(outline.tree, list)，对 dict 恒为 False，
            # 于是 outline_sections 永远是 []，ScoreCoverageSkill 直接短路返回 ""，
            # 覆盖率恒为 0%（这就是"评分覆盖检查永远 0%"的直接原因）。
            outline_sections = []
            if outline and outline.tree:
                tree = outline.tree
                if isinstance(tree, list):
                    outline_sections = tree
                elif isinstance(tree, dict):
                    outline_sections = (
                        tree.get("chapters") or tree.get("sections") or []
                    )
            logger.info(f"[评分覆盖] 项目 {project_id} 带入大纲章节 {len(outline_sections)} 个")

            from services.generate.skills.structure_template_skill import ScoreCoverageSkill

            gateway = get_llm_gateway()
            skill = ScoreCoverageSkill()
            ctx = SkillContext(
                project_id=project_id,
                db=db,
                llm=gateway,
                parameters={
                    "scoring_matrix": matrix,
                    "outline_sections": outline_sections,
                    "score_mapping": (outline.score_mapping if outline else None) or {},
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


def _outline_ancestors(tree: dict) -> dict[str, set[str]]:
    """返回 {节点id: 其全部祖先节点id集合}。"""
    result: dict[str, set[str]] = {}

    def walk(nodes: list, ancestors: list[str]) -> None:
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            nid = str(n.get("id", "")).strip()
            if nid:
                result[nid] = set(ancestors)
            walk(n.get("children") or [], ancestors + [nid])

    walk((tree or {}).get("chapters", []) or [], [])
    return result


def _build_scoring_context(tree: dict, chapter_id: str, chapter_node: dict | None) -> str:
    """给本章正文注入必须响应的评分项。

    评分项一般只映射到一级章节（如「专项服务方案」→ 某个一级目录），而正文是
    按二/三级章节逐个生成的。旧实现只认 `v == chapter_id` 精确相等，于是真正
    动笔的子章节拿不到任何评分项提示，写出来的正文自然踩不到评分点。
    这里把「本章自身 / 祖先 / 后代」命中的评分项全部带上。
    """
    if not tree or not tree.get("score_mapping"):
        return ""

    cid = str((chapter_node or {}).get("id") or chapter_id or "").strip()
    if not cid:
        return ""

    related_ids = {cid}
    related_ids |= _outline_ancestors(tree).get(cid, set())
    related_ids |= _outline_descendants(tree).get(cid, set())

    related = {
        k: v for k, v in tree["score_mapping"].items()
        if str(v) in related_ids
    }
    if not related:
        return ""

    lines = [f"- {name}（对应大纲章节 {sid}）" for name, sid in related.items()]
    return (
        "【本章必须响应的评分项】\n"
        + "\n".join(lines)
        + "\n请在正文中针对上述评分项的评分标准，逐条写出评委可以据此打分的具体内容"
        "（承诺、措施、数量、时限等），不要只写空泛口号。"
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

    from services.generate.skills.outline_gen_skill import _tokenize_chinese

    for score_name, chapter_id in score_mapping.items():
        name = str(score_name)
        # 1) 原文直接出现完整评分项名 —— 最可靠
        if name and name in full_text:
            covered += 1
            continue
        # 2) 评分项名本身带空格/逗号（如 "商务部分, 业绩"）时逐个查
        keywords = [w for w in re.split(r"[\s,，、]+", name) if len(w) >= 2]
        if keywords and all(kw in full_text for kw in keywords):
            covered += 1
            continue
        # 3) 中文没有词边界，旧实现切出来的"关键词"就是整串，等于要求字面全等。
        #    改为特征词命中率：评分项的核心特征词有一半以上出现在正文里即算覆盖。
        tokens = _tokenize_chinese(name)
        if tokens:
            hit = sum(1 for t in tokens if t in full_text)
            if hit / len(tokens) >= 0.5:
                covered += 1
                continue
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
    # 单章目标字数:0=自动(按标题推断,旧行为)
    word_count: int = 0,
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
    # 目标字数:0 时不传 word_count 键,让 Skill 走自己的 _infer_word_count 兜底
    skill_params = {
        "mode": mode,
        "chapter_title": chapter_title,
        "chapter_outline": chapter_outline[:2000],
        "chapter_context": chapter_context,
        "tender_context": tender_context,
        "scoring_context": scoring_context,
        "mandatory_requirements": mandatory_reqs,
    }
    if word_count and word_count > 0:
        skill_params["word_count"] = resolve_chapter_words(word_count, chapter_title)
    ctx = SkillContext(
        project_id=project_id,
        db=db,
        llm=gateway,
        knowledge_base=knowledge_base,
        parameters=skill_params,
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
    # 单章目标字数:0=自动(按标题推断,旧行为)
    word_count: int = 0,
    # 用 DI 会话：原来手写 db = async_session()() 从不 close()，
    # 流式请求每次都漏一条连接（get_db 会在响应结束后自动关闭）。
    # 该会话只用于取上下文，生成器内部另开 persist 会话，故不受流式生命周期影响。
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

    # 有下级章节的节点只写"本章概述",避免和下级章节内容/编号重复
    is_branch_node = bool(chapter_node and chapter_node.get("children"))
    if is_branch_node:
        target_words = OVERVIEW_WORDS
    else:
        target_words = resolve_chapter_words(word_count, chapter_title)
    system_prompt = build_chapter_system_prompt(
        chapter_title, target_words, overview=is_branch_node
    )

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
            async for chunk in gateway.stream_chat(
            messages=messages,
            temperature=0.7,
            max_tokens=max(2048, min(int(target_words * 3) + 512, 8192)),
            no_thinking=True,
        ):
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

    # 生成器内部不用这个会话（它自带 persist 会话），提前归还连接：
    # 否则整本书生成期间（可能几十分钟）会一直占着一条连接。
    await db.close()
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
            # 有子节点的分支节点只写"本章概述",正文由下级章节展开。
            # 以前分支节点也按整棵子树生成一遍,导致同一段内容和同一批编号
            # 在文档里重复出现(实测 1718 条带编号标题只有 1506 个不同值)。
            "is_parent": bool(node.get("children")),
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
    # 全书目标字数:0=不限制(退回按标题逐章推断,旧行为)
    total_words: int = 0,
    # 单章目标字数:0=自动
    word_count: int = 0,
    # 只重新生成"未加载/失败"的章节(前端"重新生成未加载内容(N 章)"按钮用)
    only_missing: bool = False,
    # 同 stream_generate_chapter：改用 DI 会话，避免手写会话不关闭导致连接泄漏
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
        raise HTTPException(status_code=400, detail="请先生成大纲")

    tree = outline.tree if isinstance(outline.tree, dict) else {}
    chapters_list = tree.get("chapters", []) if isinstance(tree, dict) else []
    if not chapters_list:
        raise HTTPException(status_code=400, detail="大纲章节为空")

    all_chapters = _collect_chapter_ids(chapters_list)
    if not all_chapters:
        raise HTTPException(status_code=400, detail="大纲中无有效章节")

    # 全量深度优先序号：sort_order 必须按**全量大纲**计算。原先这个映射在落库时
    # 才用 all_chapters 现算，而"只补缺章"会把 all_chapters 换成子集，序号塌成
    # 1..N —— 只缺第 5 章时新正文会按 sort_order=1 覆盖到第 1 章（内容与标题错位）。
    node_order = {c["id"]: i + 1 for i, c in enumerate(all_chapters)}

    # 只补缺章:重新生成按钮用 —— 判定"缺"= 没内容 / 少于 100 字 / 是失败提示或图片占位。
    # 章节落库顺序与大纲深度优先序号一致(chapters.sort_order = 序号),这里按序号匹配。
    total_all_chapters = len(all_chapters)
    if only_missing:
        _rows = await db.execute(
            select(Chapter.sort_order, Chapter.content).where(Chapter.project_id == project.id)
        )
        _existing = {int(so or 0): (c or "") for so, c in _rows.all()}
        _need: list[dict] = []
        for _idx, _info in enumerate(all_chapters, start=1):
            _text = _existing.get(_idx, "").strip()
            if len(_text) < 100 or "本章正文未能生成" in _text or "占位提示" in _text:
                _need.append(_info)
        all_chapters = _need
        logger.info("[批量生成] 只补缺章: 需要重生成 %s / 共 %s", len(all_chapters), total_all_chapters)
        if not all_chapters:
            # 注意:外层是普通 async 函数(内层 batch_event_generator 才是生成器),
            # 这里不能直接 yield,否则整个路由会变成 async generator 而报
            # "'return' with value in async generator"。
            async def _nothing_to_do():
                yield f"data: {json.dumps({'type': 'start', 'total': 0, 'only_missing': True}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'total': 0, 'completed': 0, 'failed': 0}, ensure_ascii=False)}\n\n"

            # 生成器内部自带 persist 会话，这里提前归还 DI 会话的连接
            await db.close()
            return StreamingResponse(_nothing_to_do(), media_type="text/event-stream")

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

    # 全书目标字数按"需要写正文的叶子节点"均摊;分支节点只写一段概述,不占预算。
    # (大纲里节点数远多于有效章节:实测 606 个节点、300 个已生成,若按全部节点
    #  均摊,每章预算会被稀释到失去意义。)
    leaf_count = sum(1 for c in all_chapters if not c.get("is_parent"))
    per_leaf_words = 0
    if total_words and total_words > 0 and leaf_count:
        # 篇幅校准:两轮实测拟合出"每章实际字数 ≈ 53 + 1.348 × 每章预算"
        # (预算 558 → 全书 204,052 字;预算 195 → 98,821 字)。
        # 有下级的章节固定按 OVERVIEW_WORDS 写,不吃叶子预算但占篇幅,所以先从
        # 目标总字数里扣掉这部分开销,再反解叶子章节的每章预算。
        _fixed = float(os.getenv("BMP_LEN_FIXED", "53"))
        _slope = max(0.1, float(os.getenv("BMP_LEN_SLOPE", "1.348")))
        _branch_count = max(0, len(all_chapters) - leaf_count)
        _branch_overhead = _branch_count * (_fixed + _slope * OVERVIEW_WORDS)
        _leaf_target = max(0.0, total_words - _branch_overhead)
        _need = (_leaf_target / leaf_count - _fixed) / _slope
        per_leaf_words = max(
            MIN_CHAPTER_WORDS, min(MAX_CHAPTER_WORDS, round(_need))
        )
        logger.info(
            "[批量生成] 目标总字数=%s,叶子=%s,分支=%s,分支开销≈%s,反解每章预算=%s 字",
            total_words, leaf_count, _branch_count, round(_branch_overhead), per_leaf_words,
        )

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

                    # 分支节点(有下级章节)只写本章概述,避免和下级章节重复;
                    # 叶子节点用预算分摊值,没设总字数时退回按标题推断。
                    if ch_info.get("is_parent"):
                        chapter_words = OVERVIEW_WORDS
                    elif per_leaf_words:
                        chapter_words = per_leaf_words
                    else:
                        chapter_words = resolve_chapter_words(word_count, ch_title)

                    system_prompt = build_chapter_system_prompt(
                        ch_title, chapter_words, overview=bool(ch_info.get("is_parent"))
                    )

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

                    # 首轮也给足预算:实测 303 章里有 228 章首轮返回空流(思维链把
                    # max_tokens 吃光),全部靠下面的重试救回 —— 每次重试都是额外调用。
                    _first_max_tokens = max(2048, min(int(chapter_words * 3) + 512, 8192))
                    collected = []
                    async for chunk in gateway.stream_chat(
                        messages=msgs, temperature=0.7, max_tokens=_first_max_tokens, no_thinking=True
                    ):
                        collected.append(chunk)
                    full_content = "".join(collected)
                    full_content = _post_process_stream_content(full_content, ch_title)
                    # 数据依赖章节(营业执照/银行保函/投标保证金凭证等)模型经常
                    # 一个字都不输出,流式路径以前直接写空 —— 实测 300 章里有 49 章
                    # word_count=0。这里补上占位提示,和 Skill 路径的行为对齐。
                    if len(full_content.strip()) < 50:
                        # 空流重试:换成最简指令再要一次(短任务的空流多半是
                        # 思维链吃光预算,给足 max_tokens 并去掉复杂约束)
                        try:
                            from services.generate.skills.content_gen_skill import ContentGenSkill as _CGS0
                            retry_system = (
                                f"请直接用简体中文写一段关于“{ch_title}”的本章概述，"
                                f"{max(MIN_CHAPTER_WORDS, chapter_words)} 字左右，以“本章”开头。"
                                "不要输出标题、不要输出 Markdown 标记、不要任何解释。"
                            )
                            retry_msgs = [
                                {"role": "system", "content": retry_system},
                                {"role": "user", "content": f"章节标题：{ch_title}。请开始撰写。"},
                            ]
                            retry_chunks = []
                            async for chunk in gateway.stream_chat(
                                messages=retry_msgs,
                                temperature=0.7,
                                max_tokens=max(2048, min(int(chapter_words * 3) + 512, 8192)),
                                no_thinking=True,
                            ):
                                retry_chunks.append(chunk)
                            retried = _post_process_stream_content("".join(retry_chunks), ch_title)
                            if len(retried.strip()) >= 50:
                                full_content = retried
                            elif _CGS0._is_data_dependent_chapter(ch_title):
                                full_content = _CGS0._generate_data_placeholder(ch_title)
                            else:
                                full_content = _fallback_overview(ch_title)
                            logger.info(
                                "[批量生成] 空流已补救 chapter=%s retry_len=%s final_len=%s",
                                ch_title, len(retried.strip()), len(full_content.strip()),
                            )
                        except Exception as _e:
                            logger.warning(f"[批量生成] 空流重试失败 chapter={ch_title}: {_e}")
                            full_content = _fallback_overview(ch_title)
                    return ("ok", ch_id, ch_title, full_content)
                except Exception as e:
                    return ("error", ch_id, ch_title, str(e))

        # 供应商有每分钟请求数配额:303 章全部并发会瞬间打满(实测 429 rpm exhausted,
# 244 章失败)。改成信号量限流 + 章间小间隔,可用环境变量调整。
        _concurrency = max(1, int(os.getenv("BMP_GEN_CONCURRENCY", "2")))
        _interval = float(os.getenv("BMP_GEN_INTERVAL", "2.0"))
        _sem = asyncio.Semaphore(_concurrency)

        async def _gen_limited(ch_info):
            async with _sem:
                result = await _gen_one(ch_info)
                await asyncio.sleep(_interval)
                return result

        for ch_info in all_chapters:
            gen_tasks.append(asyncio.create_task(_gen_limited(ch_info)))

        for task in asyncio.as_completed(gen_tasks):
            result = await task
            if result[0] == "ok":
                _, ch_id, ch_title, full_content = result
                all_contents[ch_id] = full_content
                completed += 1
                # 逐章播报进度: 前端 batchProgress.current 只认 type='progress' 事件,
                # 原先只发 chapter_done,分子永远是 0,进度条恒显示 0/X。
                yield f"data: {json.dumps({'type': 'progress', 'current': completed, 'total': total, 'chapter_title': ch_title}, ensure_ascii=False)}\n\n"
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

                # 节点在大纲里的深度优先序号（在函数开头按全量大纲算好，见 node_order）。
                # chapters.sort_order 用来区分同名节点 —— 大纲里有重名节点(如"授权委托书"
                # 出现在 3 处),以前只按标题匹配,303 个节点最终只落库 300 条,内容互相覆盖。
                for ch_id, ch_content in all_contents.items():
                    ch_title = _find_chapter_title_by_id(chapters_list, ch_id)
                    seq = node_order.get(ch_id, 0)
                    base_conditions = [Chapter.project_id == proj_record.id]
                    if outline:
                        base_conditions.append(Chapter.outline_id == outline.id)

                    ch_record = None
                    if seq:
                        by_seq = await persist_db.execute(
                            select(Chapter).where(*base_conditions, Chapter.sort_order == seq)
                        )
                        ch_record = by_seq.scalar_one_or_none()
                    if ch_record is None and ch_title:
                        # 兼容历史数据(sort_order 全为 0):按标题认领还没被认领的那条
                        by_title = await persist_db.execute(
                            select(Chapter)
                            .where(*base_conditions, Chapter.title == ch_title, Chapter.sort_order == 0)
                            .order_by(Chapter.created_at)
                        )
                        ch_record = by_title.scalars().first()

                    if ch_record:
                        ch_record.content = ch_content
                        ch_record.status = "generated"
                        ch_record.word_count = len(ch_content)
                        if seq:
                            ch_record.sort_order = seq
                    else:
                        new_ch = Chapter(
                            project_id=proj_record.id,
                            outline_id=outline.id if outline else None,
                            title=ch_title or ch_id,
                            content=ch_content,
                            mode=mode,
                            status="generated",
                            word_count=len(ch_content),
                            sort_order=seq,
                        )
                        persist_db.add(new_ch)
                if proj_record:
                    proj_record.status = ProjectStatus.GENERATING
                await persist_db.commit()
        except Exception as e:
            logger.warning(f"[批量生成] 内容持久化失败: {e}")

        yield f"data: {json.dumps({'type': 'done', 'total': total, 'completed': completed, 'failed': failed}, ensure_ascii=False)}\n\n"

    # 生成器内部自带 persist 会话，这里提前归还 DI 会话的连接
    await db.close()
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
                "updated_at": iso_utc(ch.updated_at),
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
    from docx.shared import RGBColor

    num_cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=num_cols)
    table.style = "Table Grid"
    for i, row_data in enumerate(rows):
        for j, cell_text in enumerate(row_data):
            if j < num_cols:
                cell = table.rows[i].cells[j]
                cell.text = cell_text
                # 需要贴图的占位说明用灰色斜体,和正式正文区分(用户要求)
                is_placeholder = "【此处需插入" in cell_text or "此处需要插入" in cell_text
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.first_line_indent = Pt(0)
                    for run in paragraph.runs:
                        run.font.name = "宋体"
                        run.font.size = Pt(10.5)
                        if is_placeholder:
                            run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
                            run.font.italic = True


def _add_markdown_to_doc(doc: Document, md_text: str):
    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # 正文里的小标题一律降到 Heading 4/5：章节标题现在按编号深度占 1~3 级，
        # 正文小标题若仍用 1~3 级，会被 TOC \o "1-3" 一起收进目录（实测混入
        # 448 条），目录因此又长又不准。字号在这里显式指定，视觉不变。
        if line.startswith("# ") and not line.startswith("## "):
            heading_text = line.lstrip("#").strip()
            heading = doc.add_heading(heading_text, level=4)
            for run in heading.runs:
                run.font.name = "宋体"
                run.font.size = Pt(13)
            i += 1
            continue

        if line.startswith("## ") and not line.startswith("### "):
            heading_text = line.lstrip("#").strip()
            heading = doc.add_heading(heading_text, level=4)
            for run in heading.runs:
                run.font.name = "宋体"
                run.font.size = Pt(12.5)
            i += 1
            continue

        if line.startswith("### ") and not line.startswith("#### "):
            heading_text = line.lstrip("#").strip()
            heading = doc.add_heading(heading_text, level=4)
            for run in heading.runs:
                run.font.name = "宋体"
                run.font.size = Pt(12)
            i += 1
            continue

        if line.startswith("#### "):
            heading_text = line.lstrip("#").strip()
            heading = doc.add_heading(heading_text, level=5)
            for run in heading.runs:
                run.font.name = "宋体"
                run.font.size = Pt(12)
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


def _q(name: str) -> str:
    """对下载文件名做百分号编码。

    Starlette 用 latin-1 编码响应头,Content-Disposition 里直接放中文会抛
    'latin-1' codec can't encode characters...,导致下载接口 500。
    """
    from urllib.parse import quote

    return quote(name)


def _strip_duplicate_heading(content: str, chapter_title: str, node_id: str = "") -> str:
    """去掉正文开头与章节标题重复的 Markdown 小标题。

    模型经常在正文第一行又把自己的标题写一遍(如 "### 11.1.2 养护目标与质量标准"),
    导出后就与一级标题的编号重复出现。实测重生成后仅剩的 3 处"重复编号"全部来自这里。
    """
    if not content:
        return content
    lines = content.split("\n")
    for idx, line in enumerate(lines[:3]):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("#"):
            break
        text = stripped.lstrip("#").strip()
        core = re.sub(r"^\d+(?:\.\d+)*[\s、.]*", "", text).strip()
        same_title = bool(core) and core == (chapter_title or "").strip()
        same_number = bool(node_id) and text.startswith(node_id + " ")
        if same_title or same_number:
            del lines[idx]
            return "\n".join(lines).lstrip("\n")
        break
    return content


def _outline_node_order(tree: dict) -> list[tuple[str, str]]:
    """按大纲树的深度优先顺序返回 [(节点id, 标题), ...]。"""
    ordered: list[tuple[str, str]] = []

    def walk(nodes: list) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            ordered.append((str(node.get("id", "") or ""), str(node.get("title", "") or "").strip()))
            children = node.get("children")
            if isinstance(children, list):
                walk(children)

    if isinstance(tree, dict):
        walk(tree.get("chapters", []) or [])
    return ordered


def order_chapters_by_outline(chapters: list, tree: dict) -> list[tuple[object, str]]:
    """把章节按大纲顺序重排,返回 [(chapter, 大纲节点id), ...]。

    为什么必须重排:chapters.sort_order 从来没被写过值(PG 实测全库
    count(distinct sort_order)=1、恒为 0),导出用的 ORDER BY sort_order
    等于没排,拿到的是数据库物理顺序 —— 300 个章节标题里 69 处逆序,
    带编号的小标题因此前后乱跳。

    大纲里存在重名节点(例如「授权委托书」同时出现在 1.3.2/2.2/4.1.3),
    这里按出现顺序依次配对尚未使用的同名章节,保证章节一个不丢。
    """
    ordered = _outline_node_order(tree if isinstance(tree, dict) else {})
    if not ordered:
        return [(ch, "") for ch in chapters]

    by_title: dict[str, list] = {}
    for ch in chapters:
        by_title.setdefault((ch.title or "").strip(), []).append(ch)

    result: list[tuple[object, str]] = []
    used: set[int] = set()
    for node_id, title in ordered:
        bucket = by_title.get(title)
        while bucket:
            ch = bucket.pop(0)
            if id(ch) in used:
                continue
            used.add(id(ch))
            result.append((ch, node_id))
            break
    # 大纲里找不到的章节(手工新增、或大纲后来改过)统一放到最后
    for ch in chapters:
        if id(ch) not in used:
            result.append((ch, ""))
    return result


def _normalize_body_headings(content: str, node_id: str, descendant_ids: set[str] | None) -> str:
    """把章节正文里的 Markdown 小标题统一到全局编号。

    模型写正文时用的是"章内相对编号"(每一章的小标题都从 1.1 开始),导出成
    Heading2/3 之后就和真实章节号撞车 —— 实测第二章出现两个 2.1、两个 2.1.1。
    - 叶子章节:按本章节点号重排为 {节点号}.1 / {节点号}.1.1 …… 全局唯一。
    - 父章节(有子节点):正文里带编号的小标题一律删掉,因为那些小节本身就是
      独立章节,留着必然与子章节的一级标题重复。
    """
    if not content:
        return content

    if descendant_ids:
        kept = [ln for ln in content.split("\n")
                if not re.match(r"^#{1,6}\s*\d", ln.strip())]
        return "\n".join(kept)

    if not node_id:
        return content

    out: list[str] = []
    counters: dict[int, int] = {}
    for line in content.split("\n"):
        m = re.match(r"^(#{3,6})\s*(.*)$", line.strip())
        if not m:
            out.append(line)
            continue
        level = len(m.group(1))
        depth = max(1, level - 2)
        raw_title = m.group(2).strip()
        title = re.sub(r"^\d+(?:\.\d+)*[\s、.]*", "", raw_title).strip() or raw_title
        counters[depth] = counters.get(depth, 0) + 1
        for key in [k for k in counters if k > depth]:
            counters.pop(key)
        number = node_id + "".join(f".{counters.get(d, 1)}" for d in range(1, depth + 1))
        out.append(f"{'#' * level} {number} {title}")
    return "\n".join(out)


def _outline_descendants(tree: dict) -> dict[str, set[str]]:
    """返回 {节点id: 其全部后代节点id集合},用于识别父章节正文里重复列出的子章节标题。"""
    result: dict[str, set[str]] = {}

    def walk(nodes: list, ancestors: list[str]) -> None:
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            nid = str(n.get("id", "")).strip()
            for a in ancestors:
                result.setdefault(a, set()).add(nid)
            walk(n.get("children") or [], ancestors + [nid])

    walk(tree.get("chapters", []) or [], [])
    return result


def _drop_descendant_headings(content: str, descendant_ids: set[str] | None) -> str:
    """删掉父章节正文里重复列出子章节的那些标题行。

    父章节(有子节点的章节)的正文经常写成 "### 2.1.1 法定代表人身份证明书"、
    "### 2.2.1 授权委托书正文" …… 把这些子章节又列了一遍;而导出时每个子章节
    本身就是一级标题,于是同一编号在文档里出现两次、层级也乱(实测第二章 5 处、
    第一章 2 处)。这里按"编号命中后代节点 id"精确删除,只删标题行、保留正文。
    """
    if not content or not descendant_ids:
        return content
    kept = []
    for line in content.split("\n"):
        m = re.match(r"^#{1,6}\s*(\d+(?:\.\d+)*)", line.strip())
        if m and m.group(1) in descendant_ids:
            continue
        kept.append(line)
    return "\n".join(kept)


def _bookmark_name(index: int) -> str:
    """目录用书签名。必须是字母开头、不含空格与点号，故用 _Toc_ 前缀 + 序号。"""
    return f"_Toc_bmp_{index:05d}"


def _add_bookmark(paragraph, name: str, bookmark_id: int) -> None:
    """把整段包进一个书签，供目录的 PAGEREF 域引用页码。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    # OOXML 规定 w:pPr 必须是 w:p 的第一个子元素：原来 insert(0) 把 bookmarkStart
    # 塞到了 pPr 前面（实测导出文件 303/303 个标题都违规），Word/WPS 可能提示修复。
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is not None:
        pPr.addnext(start)
    else:
        paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _add_page_ref(paragraph, bookmark: str, cached: str = "1") -> None:
    """在目录条目末尾插入 PAGEREF 域：打开文档自动更新后显示真实页码。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin.set(qn("w:dirty"), "true")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" PAGEREF {bookmark} \\h "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(separate)
    run._r.append(OxmlElement("w:t"))
    run._r[-1].text = cached

    run2 = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run2._r.append(end)


def _build_cover(doc, fallback_name: str, facts: dict) -> None:
    """生成投标文件封面。

    旧实现只在首页居中放一行项目名称，既没有「投标文件」字样，也没有项目编号、
    采购人和投标人、日期 —— 封面不像封面。这里按投标文件通行格式补齐：
        项目名称 / 项目编号 / 投 标 文 件 / 投标人（盖章）/ 日期
    其中项目名称、项目编号、采购人取自招标文件解读结果（analysis.dimensions
    .project_info），取不到时留出可手工填写的下划线。
    """
    from docx.oxml.ns import qn

    name = str(facts.get("project_name") or fallback_name or "").strip()
    code = str(facts.get("project_code") or "").strip()
    unit = str(facts.get("procurement_unit") or facts.get("purchaser_name") or "").strip()

    def line(text: str, size: float, bold: bool = False,
             before: float = 0, after: float = 0):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.line_spacing = 1.5
        r = p.add_run(text)
        r.font.name = "宋体"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        r.font.size = Pt(size)
        r.bold = bold
        return p

    blank = "　" * 1
    line(blank, 12, before=54)
    line(name or "（项目名称）", 22, bold=True, after=10)
    if code:
        line(f"项目编号：{code}", 14, after=4)
    if unit:
        line(f"采购人：{unit}", 14, after=4)

    line(blank, 12, before=30)
    line("投　标　文　件", 36, bold=True, before=12, after=12)
    line(blank, 12, before=30)

    line("投标人：＿＿＿＿＿＿＿＿＿＿＿＿＿＿（加盖单位公章）", 15, before=48, after=14)
    line("日　期：＿＿＿＿ 年 ＿＿ 月 ＿＿ 日", 15, after=8)

    doc.add_page_break()


def _add_export_footer(doc) -> None:
    """页脚居中页码（第 X 页）。

    导出稿原先完全没有页码（实测 PAGE 域数量为 0），目录里的页码自然无从谈起。
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False
        para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        def _styled(run):
            run.font.name = "宋体"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            run.font.size = Pt(10.5)
            return run

        _styled(para.add_run("第 "))

        run = para.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = " PAGE "
        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        run._r.append(begin)
        run._r.append(instr)
        run._r.append(separate)
        run._r.append(OxmlElement("w:t"))
        run._r[-1].text = "1"
        end_run = para.add_run()
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        end_run._r.append(end)
        _styled(run)

        _styled(para.add_run(" 页"))


def _enable_update_fields(doc) -> None:
    """让 Word/WPS 打开文档时自动更新域。

    没有这个开关，TOC / PAGEREF 只显示写入时的"缓存结果"（页码全是占位 1），
    必须手工按 F9 才对——这正是"目录页码不准"的根源。
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    settings = doc.settings.element
    el = settings.find(qn("w:updateFields"))
    if el is None:
        el = OxmlElement("w:updateFields")
        settings.append(el)
    el.set(qn("w:val"), "true")


def _add_toc(doc, ordered_chapters: list, levels: int) -> None:
    """插入目录：可见条目（含真实页码域）+ 可刷新的 TOC 域。

    旧实现有三个问题，这里一并修掉：
    1) 条目用的是普通段落，Word 不认作目录内容；现在条目之间插入 PAGEREF 域并
       配合 w:updateFields，打开即显示真实页码。
    2) 页码全是占位值且没有目录样式，刷新后与正文对不上；现在条目按层级缩进、
       右侧制表位加点线对齐页码。
    3) 正文里所有章节都被写成 Heading 1（实测 303 个），导致 TOC 域刷新后层级
       塌成一维；现在标题层级由大纲节点号深度决定，见 export_docx 的调用处。
    """
    from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    levels = max(1, min(3, levels))

    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    head.paragraph_format.space_before = Pt(6)
    head.paragraph_format.space_after = Pt(16)
    head_run = head.add_run("目　　录")
    head_run.font.name = "宋体"
    head_run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    head_run.font.size = Pt(18)
    head_run.bold = True

    # 目录正文区：Word 的 TOC 域结果区从这里开始
    field_para = doc.add_paragraph()
    field_para.paragraph_format.space_after = Pt(0)
    field_run = field_para.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin.set(qn("w:dirty"), "true")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-%d" \\h \\z \\u ' % levels
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    field_run._r.append(begin)
    field_run._r.append(instr)
    field_run._r.append(separate)

    # 版心宽按真实页面设置算（原来硬编码 21.0-3.17-3.17，只对 A4+3.17cm 边距成立；
# 页面不是 A4 或边距被改过时，目录页码点线就会偏离右边界）
    _sec = doc.sections[0] if doc.sections else None
    _pw = (_sec.page_width.cm if (_sec is not None and _sec.page_width is not None) else 21.0)
    _lm = (_sec.left_margin.cm if (_sec is not None and _sec.left_margin is not None) else 3.17)
    _rm = (_sec.right_margin.cm if (_sec is not None and _sec.right_margin is not None) else 3.17)
    usable = _pw - _lm - _rm
    for idx, (chapter, node_id) in enumerate(ordered_chapters):
        title = (chapter.title or "").strip()
        if not title:
            continue
        depth = (str(node_id).count(".") + 1) if node_id else 1
        if depth > levels:
            continue

        entry = doc.add_paragraph()
        pf = entry.paragraph_format
        pf.space_after = Pt(3)
        pf.line_spacing = 1.4
        pf.left_indent = Pt(18 * (depth - 1))
        pf.tab_stops.add_tab_stop(
            Cm(usable - 0.4), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
        )

        run = entry.add_run(f"{node_id}　{title}" if node_id else title)
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        run.font.size = Pt(12 if depth == 1 else 11)
        run.bold = depth == 1

        entry.add_run("\t")
        # 与正文标题处的书签同名（同一 idx），PAGEREF 才能取到正确页码
        _add_page_ref(entry, _bookmark_name(idx))

    end_para = doc.add_paragraph()
    end_para.paragraph_format.space_after = Pt(0)
    end_run = end_para.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    end_run._r.append(end)

    doc.add_page_break()


@router.get("/{project_id}/export-docx")
async def export_docx(
    project_id: str,
    fmt: str = Query("docx", pattern="^(docx|doc|pdf)$"),
    template: str = Query("default"),
    apply_format: bool = Query(True),
    toc: bool = Query(True),
    toc_levels: int = Query(3, ge=1, le=4),
    db: AsyncSession = Depends(get_db),
):
    # 被别的路由当普通函数直接调用时(projects.py 的"导出 Word"就是这么调的),
    # FastAPI 不会把 Query(...) 默认值解析成真正的值,参数会带着 Query 对象进来
    # —— 实测报 "'<' not supported between instances of 'Query' and 'int'"(500)。
    # 这里统一兜底:不是期望类型就取 Query 的默认值。
    if not isinstance(toc_levels, int):
        toc_levels = int(getattr(toc_levels, "default", 3) or 3)
    if not isinstance(toc, bool):
        toc = bool(getattr(toc, "default", False))
    if not isinstance(apply_format, bool):
        apply_format = bool(getattr(apply_format, "default", True))
    if not isinstance(template, str):
        template = str(getattr(template, "default", "default") or "default")
    if not isinstance(fmt, str):
        fmt = str(getattr(fmt, "default", "docx") or "docx")
    toc_levels = max(1, min(4, toc_levels))

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

    # 顺序改由大纲树决定(见 order_chapters_by_outline 的说明);
    # 返回的节点 id 同时用于给一级标题编号。
    outline_result = await db.execute(
        select(Outline).where(Outline.project_id == project.id)
    )
    outline = outline_result.scalar_one_or_none()
    outline_tree = outline.tree if outline and isinstance(outline.tree, dict) else {}
    ordered_chapters = order_chapters_by_outline(list(chapters), outline_tree)

    # 封面要用的项目事实(项目名称/项目编号/采购人)来自招标文件解读结果
    an_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    cover_facts = _extract_project_facts(an_result.scalar_one_or_none())

    doc = DocxDocument()

    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.17)
    section.right_margin = Cm(3.17)

    # 封面:项目名称 + 项目编号 + 采购人 + 「投标文件」+ 投标人 + 日期
    _build_cover(doc, project.name, cover_facts)

    if toc:
        _add_toc(doc, ordered_chapters, toc_levels)

    # 页脚页码 —— 目录的页码依赖它
    _add_export_footer(doc)
    # 打开文档即自动更新 TOC / PAGEREF 域,否则页码一直是占位值
    _enable_update_fields(doc)

    descendants_of = _outline_descendants(outline_tree)

    from docx.oxml.ns import qn as _qn

    for idx, (chapter, node_id) in enumerate(ordered_chapters):
        if chapter.title:
            # 标题层级必须与编号深度一致:以前 303 个章节全写成 Heading 1,
            # 于是 TOC 域刷新后层级塌成一维、与目录里显示的 1/1.1/1.1.1 对不上。
            depth = (str(node_id).count(".") + 1) if node_id else 1
            level = max(1, min(3, depth))
            heading_text = f"{node_id}  {chapter.title}" if node_id else chapter.title
            heading = doc.add_heading(heading_text, level=level)
            for run in heading.runs:
                run.font.name = "宋体"
                run._element.rPr.rFonts.set(_qn("w:eastAsia"), "宋体")
            # 书签供目录里的 PAGEREF 取页码
            _add_bookmark(heading, _bookmark_name(idx), idx + 1)

        if chapter.content:
            body = _strip_duplicate_heading(chapter.content, chapter.title, node_id)
            # 小标题统一到全局编号;父章节里重复列出的子章节标题直接删掉
            body = _normalize_body_headings(body, node_id, descendants_of.get(node_id))
            # 需要真实材料/图片的章节(营业执照、银行保函、保证金凭证、身份证明等):
            # 正文后附一个 1×1 表格,用灰色字写明此处需要插入什么图片。
            # 放在导出阶段做,已有章节不用重新生成就能生效。
            if _IMAGE_CHAPTER_PAT.search(chapter.title or ""):
                from services.generate.skills.content_gen_skill import ContentGenSkill as _CGS_EXPORT

                body = body.rstrip() + "\n\n" + _CGS_EXPORT._generate_data_placeholder(chapter.title)
            _add_markdown_to_doc(doc, body)

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

        # 字体统一:补齐 w:eastAsia(缺它中文会回退到主题字体,与数字的宋体不一致)、
        # 收敛中文字体(不再 仿宋_GB2312 与 宋体 混用)、西文统一 Times New Roman。
        # 放在 fmt 分支之前,docx/doc/pdf 三种格式共用同一份归一化结果。
        from services.format.font_utils import normalize_docx_fonts

        normalize_docx_fonts(docx_path)

        if fmt == "docx":
            data = docx_path.read_bytes()
            return StreamingResponse(
                io.BytesIO(data),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_q(safe_name)}.docx"},
            )

        if fmt == "pdf":
            from services.format.skills.pdf_export_skill import PdfExportSkill
            from services.routers.format_doc import _docx_to_pdf_weasyprint

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
            data = None
            if pdf_result.success and pdf_result.data and pdf_result.data.get("output_path"):
                pdf_path = Path(pdf_result.data["output_path"])
                if pdf_path.exists():
                    data = pdf_path.read_bytes()
                    try:
                        pdf_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            if not data:
                # 本机未装 LibreOffice/docx2pdf/reportlab,用 mammoth+weasyprint 兜底
                data = _docx_to_pdf_weasyprint(docx_path)
            if not data:
                raise HTTPException(status_code=500, detail="PDF 转换失败(所有策略均不可用)")
            try:
                docx_path.unlink(missing_ok=True)
            except OSError:
                pass
            return StreamingResponse(
                io.BytesIO(data),
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_q(safe_name)}.pdf"},
            )

        if fmt == "doc":
            from services.format.skills.doc_export_skill import DocExportSkill

            doc_skill = DocExportSkill()
            # LibreOffice 转换是阻塞调用（subprocess，超时 120s）：直接 await 会卡住
            # 整个事件循环（一个人导出 .doc 全站无响应），放线程里跑。
            doc_result = await asyncio.to_thread(doc_skill._try_libreoffice_doc, docx_path, export_root)
            if doc_result.get("success"):
                doc_path = Path(doc_result["output_path"])
                data = doc_path.read_bytes()
                try:
                    doc_path.unlink(missing_ok=True)
                    docx_path.unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                # 没有 LibreOffice: 直接下发 docx 字节,Word/WPS 按真实格式正常打开
                data = docx_path.read_bytes()
                try:
                    docx_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return StreamingResponse(
                io.BytesIO(data),
                media_type="application/msword",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_q(safe_name)}.doc"},
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
