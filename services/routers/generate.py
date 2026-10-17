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


def build_chapter_system_prompt(
    title: str,
    words: int,
    overview: bool = False,
    ledger_text: str = "",
    stable: bool = False,
    project_facts_text: str = "",
    content_mode: str = "",
) -> str:
    """构造单章正文的系统提示词(流式单章与批量生成共用一份)。

    stable=True 时输出"与本章无关"的稳定版本，把章节标题、目标字数、结构要求
    这些**每条请求都不同**的内容挪到调用方后面追加的 user 消息里。

    为什么需要 stable：模型服务只在**消息边界**复用前缀缓存，而且前缀必须从
    第一条消息起逐字相同。原实现把章节标题和目标字数写进了 system 提示词，
    于是 213 章就是 213 个不同的第一条消息，后面那一大段招标要求、设备参数、
    废标红线（合计上万字）永远无法命中缓存 —— 213 章等于 213 份全价输入。
    业界通行做法正是"写作规则放 system、字数等本条请求信息
    放 user"，并实测把输入成本降到约 1/8.6。

    注意：招标要求上下文是**按章节范围裁剪**过的（防设备参数串味，实测把
    串味从多处降到 0），所以它天生随章节变化；这里只把能稳定的部分稳定下来。

    关于字数:以前写的是"本章节总字数不少于 {wc} 字",而且硬性要求
    "每个三级小节不少于 500 字"。下限式约束只会让模型越写越长(实际每章
    ~2900 字),现在改成"控制在 X 字左右"并让子节数量随目标字数伸缩。

    overview=True 用于"有下级章节的分支节点":只写一段本章概述,不输出
    ###/#### 小标题。以前分支节点也按整棵子树生成,同一批编号在文档里
    重复出现(实测 1718 条带编号标题只有 1506 个不同值)。

    关于"禁止元语言":实测导出的标书里有 113 处"本章旨在…""供评标委员会逐项
    核查打分""本章内容不涉及…将在后续章节列明"—— 这是模型把本函数里的提示词
    要求当成内容写进了正文。评标专家一眼就能看出是模板/AI 生成,必须硬禁。
    只写"不要写元语言"模型会照写,所以这里给足反例并说明原因。

    关于口径:ledger_text 是全书唯一口径表(见 commitment_ledger_skill)。
    实测同一份标书质保期出现 3 种、投标有效期 3 种、到场时限 6 种说法,
    根因就是逐章独立生成时没有任何全局约束。
    """
    ledger_block = ""
    if ledger_text:
        ledger_block = f"""
【全书统一口径 —— 最高优先级，必须一字不差遵守】
{ledger_text}
以上是全书唯一口径。凡正文涉及上述任何事项，**必须与口径表完全一致**，
严禁出现第二种数字、第二种单位、第二种起算方式（例如口径表写"36个月"，
就不得在任何章节写"3年""二十四个月""不低于24个月"）。
若本章内容与口径表无关，正常撰写即可。"""

    placeholder_block = """
【占位符规范 —— 严禁编造企业数据】
凡是本公司无法从招标文件推断、必须由投标人提供的真实信息（专利号、业绩项目名称、
合同金额、人员姓名、证书编号、财务报表数字等），一律写成 `{{待填:项目}}` 形式，
例如 `{{待填:专利号}}`、`{{待填:业绩项目名称}}`、`{{待填:合同金额}}`。
【严禁】用 `ZL202310XXXXXX.X`、`某煤矿`、`某某公司`、`XXX`、`——` 这类伪数据填充，
它们会被原样带进正式投标文件，属于虚假响应。"""

    # ── 生成提示词的两条硬约束 ──
    # ① 跨章去重：
    #    「不为覆盖全局事实增加无关段落，也不在各节重复罗列项目概况、人员、设备或制度」
    # ② 事实优先级链：「材料与全局事实冲突时，以全局事实为准…
    #    禁止生成没有实际依据的引用」。
    # 为什么必须写进 system：实测我这份成稿 220 章里 **27%（59/215）** 的章节
    # 开头又把项目背景复述一遍，这是"各章自说自话、上下文不通顺"最直观的形态。
    # ── 项目基本事实（全局事实层）──
    # 全局事实**全量逐字**注入每一节的公共消息，且缺失就拒绝启动正文。
    # 我这边事实来自解读结果，同样全书恒定 → 放进 system，前缀缓存不受影响。
    facts_block = ""
    if project_facts_text:
        facts_block = project_facts_text

    # ── 内容形态（第三层：attr(7) + content_mode(5)）──
    # 按 content_mode 决定这一节的**生成任务类型**：格式表填写、人工填写、
    # 目录页、AI 生成，各不相同（attr→content_mode 由映射表强制推导）。
    # 我这里以前只把 attr/content_mode 标注进大纲、**正文链路从不读它**，
    # 后果是：报价章（manual-fill）被当成普通技术章写散文，模型顺手就把金额、
    # 税率、证书编号编出来 —— 正是"编造价格"这条红线最容易被踩的地方；
    # 格式表章（template-fill，投标函/资格证明/业绩）也会被自创结构覆盖掉
    # 招标文件给定的投标格式。
    # 处理原则：**只改指令、绝不因此跳过章节**（跳过 = 丢内容，红线）。
    mode_block = ""
    _cm = str(content_mode or "").strip()
    if _cm == "manual-fill":
        mode_block = """
【本节内容形态：人工填写（招标文件要求投标人自行填报的报价类内容）】
本节只输出格式框架与需人工填报的字段说明，**严禁编造任何数字**：
不得写出具体报价、单价、合价、总价、税率、下浮率、优惠金额（一律用
`{{待填:投标总价}}`、`{{待填:单价}}` 这类占位符）。招标文件未给出的价格构成
可以列出"需要填写的项目名称"，但不得替招标人/投标人决定数值。
不得编造证书编号、发票号、合同金额、银行账号。"""
    elif _cm == "template-fill":
        mode_block = """
【本节内容形态：按招标文件给定格式填写（投标函/资格证明/业绩等）】
必须严格对应招标文件给出的投标格式逐项填写，字段顺序、名称、单位与招标文件
一致，不要自创表格结构或增删字段。凡是需要投标人提供的真实信息（证书编号、
业绩项目名称、合同金额、人员姓名、财务报表数字），一律用 `{{待填:项目}}`
占位符，**严禁**编造或用 `XXX`、`某某`、`——` 之类伪数据填充。"""
    elif _cm == "directory-generate":
        mode_block = """
【本节内容形态：目录页】
只输出章节标题清单（保持与大纲一致的标题与编号），不要写正文叙述、
不要写说明性文字、不要写"本章旨在…"这类元语言。"""
    elif _cm == "other":
        mode_block = """
【本节内容形态：其他】
严格按招标文件对本节的原文要求直接陈述，不要自创章节结构，
不要添加招标文件未要求的承诺或表格。"""

    dedup_block = """
【跨章分工与去重 —— 本章不是独立文档】
- 不得为了"把本章写满"而增加与本章主题无关的段落；
- 【严禁】在本章重复罗列项目概况、招标编号、设备清单、公司简介、人员配置、
  管理制度 —— 这些是其他章节的职责，本章确有必要时只用一句话带过；
- 本章内容凡与【全书统一口径】冲突，一律以口径表为准；
- 【严禁】生成没有实际依据的引用、标准号、型号、案例或数据。"""

    if overview:
        return f"""你是具有十年以上经验的资深投标文件撰写专家。请为“{title}”这一章撰写本章概述。
{ledger_block}{facts_block}{mode_block}{dedup_block}
【要求】
1. 只写一段本章概述,{MIN_CHAPTER_WORDS}-{max(MIN_CHAPTER_WORDS + 200, words)} 字,说明本章要解决什么问题、包含哪些下级内容。
2. 【严禁】输出任何 ### 或 #### 小标题(下级内容由各自的章节展开,不要在本章重复)。
3. 【严禁】重复下级章节的内容,不要罗列细节措施。
4. 使用正式、严谨的投标文件语言,用“本公司”“投标人”指代己方。
5. 不得编造企业名称、资质证书、项目案例、人员信息、合同金额。
6. 直接输出概述正文,不要输出章节标题,不要输出任何解释或说明。
7. 概述的职责就是交代**本章的范围与下级分工**，这一点必须写清楚（例如
   “本方案覆盖…，其中…由下级各节分别展开”）。但【严禁】出现向评委解说的套话：
   “供评标委员会”“供评委逐项核查打分”“为评委打分提供依据”“便于评委”
   “评审依据”“本章内容不涉及…将在后续章节列明”。
   开头也不要写“本章旨在…”“本章将…”“本章围绕…”“本章从…出发”这类套头，
   直接从**实质范围**切入（例如“端头及超前支护装备分为…，本方案覆盖…，
   其中…由下级各节分别展开”）。
   注意与下级章节划清边界：只讲"这一章负责哪一块"，不要罗列下级章节的细节措施。"""

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
    if stable:
        # 稳定版：目标字数与结构要求由调用方在本条请求末尾的
        # 【本章任务】消息里给出，这里只保留不变的写作规范。
        title = "本章"
        structure_rule = (
            "   - 结构要求以本条请求末尾【本章任务】里给出的二级节/三级小节数量为准\n"
            "   - 可适当使用表格展示对比、清单、计划等结构化信息\n"
            "   - 【严禁】使用 ##### 或更深的小标题(最多用到 #### )\n"
        )
        _len_rule = (
            f"   - 本章节总字数以本条请求末尾【本章任务】给出的目标字数为准\n"
            "   - 【重要】不得少于该目标字数的下限。去掉下限后模型会明显少写"
            "(实测目标 12 万字只写出 7.2 万字)\n"
            "   - 【严禁】为了凑字数而重复相同句子、重复段落或堆砌同义排比\n"
            "   - 写完目标字数即可收尾\n"
        )
    else:
        _len_rule = (
            f"   - 本章节总字数控制在 {words} 字左右，合理范围 {lo}-{hi} 字\n"
            f"   - 【重要】不得少于 {lo} 字。去掉下限后模型会明显少写(实测目标 12 万字只写出 7.2 万字)\n"
            "   - 【严禁】为了凑字数而重复相同句子、重复段落或堆砌同义排比\n"
            f"   - 写完目标字数即可收尾，超出 {hi} 字视为不合格\n"
        )
    return f"""你是具有十年以上经验的资深投标文件撰写专家。请撰写“{title}”章节。
{ledger_block}{facts_block}{mode_block}{dedup_block}
【撰写规范】
1. 结构要求：
{structure_rule}   - 可适当使用表格展示对比、清单、计划等结构化信息
   - 【严禁】使用 ##### 或更深的小标题(最多用到 #### )

2. 语言风格：
   - 使用正式、严谨、专业的投标文件语言
   - 使用“本公司”、“投标人”指代己方，“采购人”、“招标人”指代对方
   - 【严禁元语言】不要写“本章旨在…”“本章围绕…”“本章将…”“本章内容涵盖…”
     “为评标委员会…”“供评委逐项核查打分”“便于评委…”“本章内容不涉及…
     将在后续章节分别列明”—— 这些是对评委解说本章结构的话，不是投标内容。
     直接写措施、承诺、参数、流程即可。实测一份标书里这类句子有 113 处，
     评标专家会直接判定为模板化/AI 生成，必须完全避免。
   - 禁止口语化表达、禁止“我们”、“你们”
   - 禁止模糊表述如“如有需要”、“可以考虑”、“大概”
   - 【严禁AI味连接词】不要用“首先/其次/再次/最后”“综上所述”“总而言之”
     “值得注意的是”“不难看出”“众所周知”“随着…的不断发展”“在当今社会”
     “为了更好地…”“本文”“让我们”这类空转连接词与套话开头，直接写实质内容。
     标书正文应当是"措施+参数+流程+标准"，不是作文。实测这类词会被评标专家
     直接判定为 AI 生成，属于降分项。

3. 内容要求：
   - 每个要点必须展开论述，给出具体措施、方法、流程或标准
   - 技术方案章节应包含：总体设计思路、技术架构、关键技术、实施方案、质量保障
   - 服务方案章节应包含：服务体系、服务内容、服务流程、服务标准、应急预案
   - 管理方案章节应包含：组织架构、管理制度、人员配置、培训计划、考核机制

4. 禁止事项：
   - 不得编造企业名称、资质证书、项目案例、人员信息、合同金额
   - 不得使用代码块包裹正文
   - 表格内不得出现 Markdown 格式标记
   - 【严禁】同一份技术参数在本章内出现两个不同数值（如一处写 3200kN、
     另一处写 280kN）。一个参数只能给一个值，且必须与上文【全书统一口径】一致。
{placeholder_block}
5. 篇幅要求（重要）：
{_len_rule}

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
                if scoring_dim:
                    # 旧实现直接 item.get("score", 0)：招标解读给的评分项只有
                    # name + description，分值是写在描述里的（"2分/项，最高10分"），
                    # 于是送给大纲模型的每一项都是 0 分（分值信息全丢）。
                    # extract_score_items 会从描述里解析分值，并兼容"只有权重"的形状。
                    from services.generate.skills.structure_template_skill import (
                        extract_score_items,
                    )

                    _score_items = extract_score_items(scoring_dim)
                    if _score_items:
                        scoring_matrix = {"rows": [
                            {
                                "category": _it.get("category") or "",
                                "item": _it["name"],
                                "score": _it.get("score") or 0,
                                "criteria": _it.get("criteria") or "",
                            }
                            for _it in _score_items
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

            # 把"用户选的生成范围"变成大纲的硬约束。
            # 以前这个选择只是个提示，提示词里还硬写着"必须包含投标函、资格审查、
            # 技术方案、商务报价"，所以选技术标也照样生成完整投标文件。
            _scope_req = ""
            try:
                from services.generate.skills.chapter_attrs import scope_requirement

                _scope_req = scope_requirement(
                    (project.config or {}).get("selected_structure_type")
                )
                logger.info(
                    "[大纲生成] 生成范围约束=%s",
                    ((project.config or {}).get("selected_structure_type") or "all"),
                )
            except Exception as _se:
                logger.warning("[大纲生成] 生成范围约束构造失败: %s", _se)

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
                    "scope_requirement": _scope_req,
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

                # 给每个一级目录打上 attr(7值) + content_mode(5值)，并做生成范围断言。
                # 这样"哪些章是技术标"从生成大纲那一刻起就是可校验数据，
                # 而不是只存在于用户点过哪个按钮里。
                try:
                    from services.generate.skills.chapter_attrs import classify_tree

                    _attr_report = classify_tree(
                        outline_data, (project.config or {}).get("selected_structure_type")
                    )
                    outline_data["chapter_attrs"] = {
                        "outline_mode": _attr_report["outline_mode"],
                        "attr_counts": _attr_report["attr_counts"],
                        "issues": _attr_report["issues"],
                    }
                    logger.info(
                        "[大纲生成] 章节属性 mode=%s 一级目录=%d 分布=%s 问题=%s",
                        _attr_report["outline_mode"], _attr_report["total_top_level"],
                        _attr_report["attr_counts"], _attr_report["issues"] or "无",
                    )
                except Exception as _ae:
                    logger.warning("[大纲生成] 章节属性标注失败(不影响大纲): %s", _ae)

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
            # 结构模板要参考"投标文件格式"章节，那部分常常在招标文件后半段，
            # 原来的 [:4000] 根本取不到（实测"投标文件格式"首现于第 4668 字）。
            tender_text = _build_tender_context(doc.parsed_content, budget=16000) if doc and doc.parsed_content else ""

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
                parameters={"document_text": _build_tender_context(doc.parsed_content, budget=30000)},
            )
            skill_result = await skill.safe_execute(ctx)

            # 落库：以前提取结果只作为任务返回值返回，**从不写入数据库**，
            # 于是每次生成正文都得靠 _extract_mandatory_requirements 从
            # analysis.dimensions 里现找 —— 而那里根本没有这些键（实测返回 ""）。
            # 现在把结果并入 analysis.dimensions["mandatory_requirements"]，
            # 让正文生成真正拿得到强制性要求。
            if skill_result.success and skill_result.data:
                try:
                    an_result = await db.execute(
                        select(Analysis).where(Analysis.project_id == project.id)
                    )
                    analysis = an_result.scalar_one_or_none()
                    payload = skill_result.data if isinstance(skill_result.data, dict) else {}
                    items = payload.get("requirements") or payload.get("items") or payload.get("mandatory_requirements")
                    if analysis is not None and items:
                        from services.generate.skills.norm_rules import fix_cn_amounts_in
                        dims = dict(fix_cn_amounts_in(analysis.dimensions or {}) or {})
                        dims["mandatory_requirements"] = items
                        analysis.dimensions = dims
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(analysis, "dimensions")
                        await db.commit()
                        logger.info("[强制性要求提取] 已落库 %s 条", len(items))
                except Exception as e:
                    logger.warning("[强制性要求提取] 落库失败: %s", e)

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


def build_chapter_task_block(
    title: str,
    words: int,
    overview: bool = False,
    writing_focus: str = "",
    chapter_path: str = "",
) -> str:
    """本条请求专属内容（章节标题 / 目标字数 / 结构要求）—— 追加在消息末尾。

    必须放在末尾：稳定内容在前、变化内容在后，前面上万字的共同上下文才能被
    模型服务的前缀缓存命中。通行规则是"模型服务只在消息边界复用
    前缀缓存，同一条消息内的相同前缀不会命中"，并据此把写作规则放 system、
    把本条请求的字数要求放 user 消息。

    writing_focus / chapter_path 来自**编排阶段**（content_plan_skill）：
      · `chapter_path` —— 祖先标题链，让模型知道自己站在全书哪条分支上；
      · `writing_focus` —— 本节写作重点与边界，system 中写明
        「本节内容范围以标题、章节描述和编排重点为准」。
    这两个字段是"跨章不重复、边界清晰"的主要依据，也是一次全书视野决策的产物。
    """
    lo = max(MIN_CHAPTER_WORDS, int(words * 0.8))
    hi = int(words * 1.25)
    if overview:
        _min = MIN_CHAPTER_WORDS
        _max = max(MIN_CHAPTER_WORDS + 200, words)
        _w = f"{_min}-{_max} 字"
        _s = "只写一段本章概述，【严禁】输出任何 ### 或 #### 小标题。"
    elif words <= 800:
        _min = lo
        _w = f"{lo}-{hi} 字"
        _s = "写 1-2 个二级节（### 标记），每个二级节下 1-2 个三级小节（#### 标记）。"
    elif words <= 1800:
        _min = lo
        _w = f"{lo}-{hi} 字"
        _s = "写 2-3 个二级节（### 标记），每个二级节下 2 个左右三级小节（#### 标记）。"
    else:
        _min = lo
        _w = f"{lo}-{hi} 字"
        _s = ("至少 3 个二级节（### 标记），每个二级节下至少 2-3 个三级小节"
              "（#### 标记）。")
    parts = ["【本章任务 —— 以下为本次请求专属要求】"]
    if chapter_path:
        parts.append(f"本章在全书中的位置：{chapter_path}")
    parts.append(f"章节标题：{title}")
    if writing_focus:
        parts.append(f"本节编排重点（内容范围以此为准，不得越界到相邻章节）：{writing_focus}")
    parts.append(f"目标字数：{_w}，【重要】不得少于 {_min} 字")
    parts.append(f"结构要求：{_s}")
    parts.append(f"请撰写“{title}”章节的完整正文。")
    return "\n".join(parts)


def _dfs_node_ids(chapters_list: list, depth: int = 1) -> list[tuple[str, int, str]]:
    """按大纲深度优先序展开，返回 [(节点id, 层级, 标题)]。"""
    out: list[tuple[str, int, str]] = []
    for n in chapters_list or []:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "")
        if nid:
            out.append((nid, depth, str(n.get("title") or "")))
        out.extend(_dfs_node_ids(n.get("children") or [], depth + 1))
    return out


def build_prior_context_block(
    ch_id: str,
    chapters_list: list,
    all_contents: dict[str, str],
    max_prev: int = 3,
    max_sibling: int = 3,
    head_chars: int = 120,
) -> str:
    """把"前面几章已经写了什么"做成紧凑摘要，注入本章提示词。

    ── 为什么必须有这一段 ──
    实测成稿 220 章里只有 **2 章（1%）** 含"承接/前述/综上"这类衔接表达，
    而 **27%（59/215）** 的章节正文开头又把项目背景复述一遍。根因是
    `all_contents`（各章正文）过去只在**全部生成完之后**的终检与评分覆盖里
    使用，**从不回灌给生成中的章节** —— 每一章都是在完全不知道别人写了什么
    的情况下独立生成的，所以读起来像 213 篇独立文档装订在一起。

    做法：取本章之前（深度优先序）已写好的最近若干章 + 同父节点下已写好的
    兄弟章，给出"标题 + 开头一句话"，并明确要求承接、去重、不复述背景。
    放在【本章任务】之前，逐字稳定的前缀缓存不受影响（变化内容本来就在尾部）。
    """
    if not all_contents:
        return ""
    order = _dfs_node_ids(chapters_list)
    idx = next((i for i, (nid, _, _) in enumerate(order) if nid == ch_id), None)
    if idx is None or idx == 0:
        return ""

    def _digest(nid: str, title: str) -> str:
        body = re.sub(r"\s+", " ", (all_contents.get(nid) or "")).strip()
        body = re.sub(r"^#{1,6}\s*", "", body)
        return f"· {title}：{body[:head_chars]}"

    # ① 本章之前最近已写好的章节（提供"刚讲过什么"，便于承接）
    prev_lines: list[str] = []
    prev_ids: set[str] = set()
    for nid, _lvl, title in reversed(order[:idx]):
        if nid in all_contents and (all_contents.get(nid) or "").strip():
            prev_lines.append(_digest(nid, title))
            prev_ids.add(nid)
            if len(prev_lines) >= max_prev:
                break
    prev_lines.reverse()

    # ② 同一父节点下、位于本章之前已写好的兄弟章（避免组内重复）
    #    已在①里出现过的必须排除：否则同一章在提示词里出现两次，
    #    既浪费字数，也让"内容边界"的指引变模糊。
    sib_lines: list[str] = []
    for nid, lvl, title in order[:idx]:
        if nid in prev_ids:
            continue
        if lvl == order[idx][1] and nid in all_contents and (all_contents.get(nid) or "").strip():
            sib_lines.append(_digest(nid, title))
    sib_lines = sib_lines[-max_sibling:]

    if not prev_lines and not sib_lines:
        return ""

    parts = [
        "【已写章节 —— 承接与去重依据】",
        "以下章节在本文件中位于本章之前，已经写完。写作时必须遵守：",
        "① 不要重复它们已经讲过的内容；同一事项确需再次提及时，"
        "用“如前所述”“在上一节已明确的……基础上”一笔带过，严禁整段复述；",
        "② 本章开头要与前面的章节自然衔接，使用承接性表述"
        "（如“在……基础上”“针对上一节确定的……”“承接前述……”），"
        "**不要重新介绍项目背景、招标编号、设备清单**；",
        "③ 全书口径必须唯一：工期、质保期、投标有效期、报价方式、"
        "设备参数一律以【全书统一口径】为准，不得出现第二种说法。",
    ]
    if prev_lines:
        parts.append("\n前面最近的章节：")
        parts.extend(prev_lines)
    if sib_lines:
        parts.append("\n同一上级下已经写好的兄弟章节（内容边界以此划分，避免互相重复）：")
        parts.extend(sib_lines)
    return "\n".join(parts)


def _iter_outline_nodes(chapters: list, depth: int = 1):
    """深度优先遍历大纲，产出 (节点, 层级)。"""
    for n in chapters or []:
        if not isinstance(n, dict):
            continue
        yield n, depth
        yield from _iter_outline_nodes(n.get("children") or [], depth + 1)


def _content_plan_enabled() -> bool:
    """编排阶段开关（默认开启）。

    BMP_CONTENT_PLAN=0 可关闭。默认开启是因为它是"跨章不重复、边界清晰"的
    主要机制（content_plan）；但它是**额外的一次模型调用**，若某次
    生成想省成本或模型限流，可以关掉，正文链路不会因此失败。
    """
    v = (os.getenv("BMP_CONTENT_PLAN") or "1").strip().lower()
    return v not in ("0", "false", "off", "no")


async def _persist_outline_plans(outline_id: str, chapters_list: list) -> None:
    """把编排结果随大纲落库，重启/续跑可复用，不必重复调用模型。"""
    if not outline_id:
        return
    from services.database import async_session
    factory = async_session()
    async with factory() as db:
        res = await db.execute(select(Outline).where(Outline.id == outline_id))
        row = res.scalars().first()
        if row is None:
            return
        tree = dict(row.tree or {})
        # JSON 列必须整体重新赋值才会被 SQLAlchemy 判定为脏数据
        tree["chapters"] = chapters_list
        row.tree = tree
        await db.commit()


async def _load_project_outline(db, project_id: str):
    result = await db.execute(
        select(Outline).where(Outline.project_id == project_id).order_by(Outline.created_at.desc())
    )
    return result.scalars().first()


@router.get("/{project_id}/chapter-attrs")
async def get_chapter_attrs(project_id: str, db: AsyncSession = Depends(get_db)):
    """回答"这份标书里到底哪些章是技术标"。

    返回每个一级目录的 attr（7 值）与由它强制推导出的 content_mode（5 值），
    以及生成范围断言（技术标独立成册时列出混进来的非技术章节）。
    只读，不改库。
    """
    outline = await _load_project_outline(db, project_id)
    if not outline:
        raise HTTPException(status_code=404, detail="项目还没有大纲")
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    config = (getattr(project, "config", None) or {}) if project else {}
    from services.generate.skills.chapter_attrs import classify_tree

    report = classify_tree(outline.tree or {}, config.get("selected_structure_type"))
    report["project_id"] = project_id
    return report


@router.post("/{project_id}/chapter-attrs")
async def rebuild_chapter_attrs(project_id: str, db: AsyncSession = Depends(get_db)):
    """重算并落库章节属性（attr / content_mode）。

    这条接口的意义：不用重新生成大纲，就能把已有标书的"这章是不是技术标"
    变成可校验数据。attr 是 AI 给初值 + 用户逐条确认
    + 程序强制推导；本接口负责"重算 + 落库 + 报告问题"，人工确认由前端/调用方
    通过传入 overrides 完成。
    """
    outline = await _load_project_outline(db, project_id)
    if not outline:
        raise HTTPException(status_code=404, detail="项目还没有大纲")
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    config = (getattr(project, "config", None) or {}) if project else {}

    tree = dict(outline.tree or {})
    from sqlalchemy.orm.attributes import flag_modified
    from services.generate.skills.chapter_attrs import classify_tree

    report = classify_tree(tree, config.get("selected_structure_type"))
    tree["chapter_attrs"] = {
        "outline_mode": report["outline_mode"],
        "attr_counts": report["attr_counts"],
        "issues": report["issues"],
    }
    outline.tree = tree
    flag_modified(outline, "tree")
    await db.commit()
    logger.info(
        "[章节属性] 已落库 project=%s mode=%s 一级目录=%d 非技术=%d 问题=%d",
        project_id, report["outline_mode"], report["total_top_level"],
        len(report["non_technical"]), len(report["issues"]),
    )
    report["project_id"] = project_id
    report["persisted"] = True
    return report


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
    # points 是"因大纲深度封顶而被折叠掉的更深层标题"（见 outline_gen_skill._prune_outline_depth）。
    # 传给模型当写作要点，让那一章把这些点写进正文段落，而不是丢掉或变成五级标题。
    points = node.get("points")
    if isinstance(points, list):
        for pt in points:
            if str(pt).strip():
                lines.append(f"{prefix}  · 需覆盖要点：{str(pt).strip()}")
    for child in node.get("children", []):
        if isinstance(child, dict):
            lines.append(_describe_node_tree(child, indent + 1))
    return "\n".join(lines)


def _node_line(node: dict, indent: str = "", desc_limit: int = 80) -> str:
    """大纲节点渲染成"- id 标题 + 缩进描述"。

    带 description 是刻意的做法：给每个叶子节点传
    parent_chapters / sibling_chapters，且**每条都带 description**，
    让模型知道"同级那几节各自负责什么"从而主动避开重复。旧实现只给了
    标题，模型看不出一节和另一节的边界，车轱辘话就来了。
    """
    line = f"{indent}- {node.get('id', '')} {node.get('title', '')}"
    desc = str(node.get("description") or "").strip().replace("\n", " ")
    if desc:
        if len(desc) > desc_limit:
            desc = desc[:desc_limit].rstrip() + "…"
        line += f"\n{indent}  {desc}"
    return line


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
        parent_desc = _node_line(parent_node)
        if parent_node.get("children"):
            parent_desc += "\n" + "\n".join(
                _node_line(c, indent="  ")
                for c in parent_node.get("children", [])
                if isinstance(c, dict)
            )
        parts.append(f"【上级章节】\n{parent_desc}")
    if sibling_nodes:
        sibling_lines = [
            _node_line(s)
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
        "【本章应当覆盖的评分项】\n"
        + "\n".join(lines)
        + "\n请针对上述评分项写出实质内容（承诺、措施、数量、时限、流程），"
        "确保每条都有可核对的具体表述。"
        # 旧措辞是"逐条写出评委可以据此打分的具体内容"，模型会把这句复述进正文，
        # 产出"…供评标委员会逐项核查打分"这类元语言（实测 113 处）。不要提"评委/打分"。
    )


# 招标解读（tender_interpret_skill）实际落库的 dimensions 结构是
# {qualification, technical, scoring, disqualification, deposit, opening, ...}，
# 废标红线/实质性要求全在 disqualification 里。旧实现只查
# ("mandatory", "mandatory_requirements", "必须响应", "强制性要求")，
# 这些键**在真实数据里一个都不存在** —— 线上两个项目实测该函数返回 ""，
# 也就是说"必须响应的强制性要求"这一整段从未进入过正文提示词。
_DQ_DIM_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("disqualification", ("disqualification_clauses", "mandatory_conditions", "substantive_requirements")),
    ("qualification", ("hard_qualifications", "other_requirements")),
    ("technical", ("mandatory_params",)),
)


def _extract_mandatory_requirements(analysis: Analysis | None) -> str:
    """抽出"废标红线 / 实质性要求 / 强制性参数"，供正文提示词注入。"""
    if not analysis or not analysis.dimensions:
        return ""
    dims = analysis.dimensions
    lines: list[str] = []

    for dim_name, keys in _DQ_DIM_KEYS:
        dim = dims.get(dim_name)
        if not isinstance(dim, dict):
            continue
        for key in keys:
            val = dim.get(key)
            if isinstance(val, str) and val.strip():
                lines.append(f"- [{dim_name}] {val.strip()}")
            elif isinstance(val, list):
                for it in val:
                    if isinstance(it, dict):
                        # 关键技术参数是 {"item": "...", "required": "..."} 形态，
                        # 要把参数名和指标拼起来，否则只抽出指标值、丢掉参数名。
                        item_name = it.get("item") or it.get("name") or it.get("param") or ""
                        required = it.get("required") or it.get("requirement") or ""
                        if item_name and required:
                            lines.append(f"- [{dim_name}] {item_name}：{required}")
                            continue
                        txt = (it.get("description") or it.get("content")
                               or it.get("requirement") or it.get("clause")
                               or it.get("text") or it.get("detail") or "")
                        if not txt:
                            # 结构不确定时兜底：取该条里最长的字符串值
                            strs = [v for v in it.values() if isinstance(v, str) and v.strip()]
                            txt = max(strs, key=len) if strs else ""
                        num = it.get("clause_number") or it.get("id") or it.get("no") or ""
                        txt = f"{num} {txt}".strip()
                    else:
                        txt = str(it)
                    if txt.strip():
                        lines.append(f"- [{dim_name}] {txt.strip()}")

    # 兼容旧结构（历史项目可能落在别的键上）
    for key in ("mandatory", "mandatory_requirements", "必须响应", "强制性要求"):
        items = dims.get(key)
        if isinstance(items, list):
            for item in items:
                desc = item.get("description", item.get("content", "")) if isinstance(item, dict) else str(item)
                if desc and desc.strip():
                    lines.append(f"- {desc.strip()}")

    if not lines:
        risk_flags = dims.get("risk_flags")
        if isinstance(risk_flags, list):
            for flag in risk_flags:
                desc = flag.get("description", flag.get("content", "")) if isinstance(flag, dict) else str(flag)
                if desc and desc.strip():
                    lines.append(f"- [风险] {desc.strip()}")
    return "\n".join(lines)


# 招标文件里与"会不会废标"直接相关的章节特征词。正文生成用的上下文窗口里
# 必须包含这些章节，否则模型根本看不到废标红线。
_TENDER_KEY_SECTIONS = (
    "废标", "无效投标", "投标无效", "符合性审查", "资格性审查", "响应性",
    "投标文件格式", "投标文件的组成", "投标文件应包括", "投标文件应包含",
    "评标办法", "资格审查", "密封", "签字盖章", "★", "▲",
)


def _build_tender_context(parsed: str, budget: int = 24000, head: int = 4000) -> str:
    """构造正文生成用的招标文件上下文。

    旧实现是 `doc.parsed_content[:4000]`，再在装配消息时截到 `[:3000]`。
    实测（线上两个项目的招标文件）：
        项目「端头及超前支护技术研究与应用」原文 67510 字，
        "废标" 首次出现在第 14909 字、"投标文件格式" 在第 4668 字 ——
        **全部落在 3000 字窗口之外**，0 次出现在模型可见范围内。
        项目「7777」原文 13735 字，"废标" 在 4825、"符合性审查" 在 4646 —— 同样看不到。
    所以模型写出来的是"看起来专业的方案"，而不是"能过符合性审查的投标文件"。

    新策略：① 头部保留 head 字（项目概况、资格要求通常在前面）；
            ② 全文按段扫描，命中关键章节词的整段抽出来附在后面；
            ③ 总量封顶 budget。
    """
    if not parsed:
        return ""
    parts = [parsed[:head]]
    seen: set[str] = set()
    for para in re.split(r"\n{2,}", parsed):
        p = para.strip()
        if len(p) < 20 or len(p) > 1500 or p in seen:
            continue
        if any(k in p for k in _TENDER_KEY_SECTIONS):
            parts.append(p)
            seen.add(p)
    if len(parts) == 1:
        return parsed[:budget]
    merged = (
        parts[0]
        + "\n\n===== 关键条款摘录（废标/符合性审查/投标文件格式/强制性参数） =====\n\n"
        + "\n\n".join(parts[1:])
    )
    return merged[:budget]


def _analysis_digest(analysis: Analysis | None) -> str:
    """把招标解读结果压成一段文本，供口径台账提炼使用。"""
    if not analysis:
        return ""
    chunks: list[str] = []
    dims = analysis.dimensions if isinstance(analysis.dimensions, dict) else {}
    for key in ("project_info", "qualification", "technical", "scoring",
                "disqualification", "deposit", "opening", "commercial", "timeline"):
        val = dims.get(key)
        if val:
            chunks.append(f"[{key}] {json.dumps(val, ensure_ascii=False)[:2500]}")
    if analysis.scoring_matrix:
        chunks.append(f"[scoring_matrix] {json.dumps(analysis.scoring_matrix, ensure_ascii=False)[:2500]}")
    return "\n".join(chunks)


LEDGER_PROMPT_HEADER = (
    "【全书统一口径 —— 最高优先级】\n"
    "下列事项全书只能有一种说法，任何章节都不得出现第二种数字/单位/起算方式："
)


def _format_ledger(ledger: dict | None) -> str:
    """把口径台账格式化成可注入提示词的文本。"""
    if not ledger or not isinstance(ledger, dict):
        return ""
    lines: list[str] = []
    for item in ledger.get("items") or []:
        if not isinstance(item, dict):
            continue
        label, value = str(item.get("label") or "").strip(), str(item.get("value") or "").strip()
        if not label:
            continue
        note = str(item.get("note") or "").strip()
        if value:
            lines.append(f"- {label}：{value}" + (f"（{note}）" if note else ""))
        else:
            lines.append(f"- {label}：招标文件未明确，由本公司统一承诺后全书一致" + (f"（{note}）" if note else ""))
    for p in ledger.get("key_params") or []:
        if isinstance(p, dict) and p.get("item"):
            lines.append(f"- 关键技术参数 {p.get('item')}：{p.get('required') or '按招标文件要求'}")
    for p in ledger.get("prohibited") or []:
        lines.append(f"- 【禁止】{p}")
    if not lines:
        return ""
    return LEDGER_PROMPT_HEADER + "\n" + "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# 作用域隔离 + 设备参数锁定 + 生成后确定性修复
#
# 原实现把整份招标要求和全部废标红线**无差别注入每一章**，实测后果：
#   · 纯技术章 4.5.1 结尾在写"投标保证金80000元、纸质一正二副、U盘1份、胶装"
#   · 备件明细表在 12 个章节里被原样粘贴十余遍
#   · 端头支架章节写成了端尾支架的参数（招标文件里 3 台设备有 6 组不同的
#     初撑力/工作阻力，全量广播后模型无法归属，只能猜）
# 下面三件事一起解决：生成时按作用域裁剪上下文、按标的物只注入对应参数表、
# 生成后用确定性规则把漏网的错误值改回锁定值。
# ══════════════════════════════════════════════════════════════════════════

async def _get_or_build_specs(
    db: AsyncSession,
    outline: Outline | None,
    tender_text: str,
    gateway=None,
    force: bool = False,
) -> dict:
    """取（或生成）按标的物切分的技术规格，缓存在 outline.tree["device_specs"]。"""
    from services.generate.skills.tender_specs import build_device_specs

    target = None
    if outline is not None:
        try:
            row = await db.execute(select(Outline).where(Outline.id == outline.id))
            target = row.scalar_one_or_none()
        except Exception as e:
            logger.warning("[设备规格] 重取大纲失败: %s", e)
    if target is None:
        target = outline
    if target is not None and not force:
        cached = (target.tree or {}).get("device_specs")
        if isinstance(cached, dict) and cached:
            return cached
    llm = gateway
    if llm is None:
        try:
            from services.llm.gateway import get_llm_gateway
            llm = get_llm_gateway()
        except Exception:
            llm = None
    specs = await build_device_specs(tender_text or "", llm=llm)
    if target is not None and specs:
        try:
            tree = dict(target.tree or {})
            tree["device_specs"] = specs
            target.tree = tree
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(target, "tree")
            await db.commit()
        except Exception as e:
            logger.warning("[设备规格] 缓存失败: %s", e)
    logger.info("[设备规格] 得到 %d 个标的物参数表", len(specs))
    return specs


def _build_repair_ctx(
    tender_text: str,
    ledger: dict | None,
    specs: dict | None,
) -> dict:
    """组装生成后修复所需的上下文。"""
    from services.generate.skills.bid_consistency import (
        allowed_amounts, build_exclusive_terms,
    )
    return {
        "tender_text": tender_text or "",
        "specs": specs or {},
        "allowed": allowed_amounts(ledger),
        "exclusive": build_exclusive_terms(specs) if specs else {},
        # 口径台账也带进单章修复上下文，让"单章重生成"和"批量生成"得到的
        # 数字归一瞬间一致（否则单章重生成会把已归一的数字又写回冲突值）。
        "ledger": ledger or None,
    }


async def _repair_whole_book(
    project_id: str,
    tender_text: str,
    ledger: dict | None,
    specs: dict | None,
) -> "object | None":
    """全书一致性收尾修复，只回写内容确实变了的章节。

    为什么必须整本来一遍：逐章修复时看不到其它章节，跨章重复的内容
    （实测同一张备件明细表被 12 个章节各粘贴一遍）发现不了。
    """
    from sqlalchemy import select as _select
    from services.database import async_session as _session
    from services.models import Chapter as _Chapter
    from services.generate.skills.bid_consistency import repair_bid

    factory = _session()
    async with factory() as db:
        rows = (await db.execute(
            _select(_Chapter.id, _Chapter.title, _Chapter.content, _Chapter.sort_order)
            .where(_Chapter.project_id == project_id)
            .order_by(_Chapter.sort_order)
        )).all()
        if not rows:
            return None
        report = repair_bid(
            [{"title": t or "", "content": c or "", "sort_order": so} for _i, t, c, so in rows],
            specs=specs or {}, ledger=ledger, tender_text=tender_text,
        )
        _fixed = {r.sort_order: r for r in report.chapters}
        written = 0
        for cid, _t, content, so in rows:
            r = _fixed.get(int(so or 0))
            if r is None or r.content == (content or ""):
                continue
            ch = (await db.execute(
                _select(_Chapter).where(_Chapter.id == cid)
            )).scalar_one_or_none()
            if ch is None:
                continue
            ch.content = r.content
            ch.word_count = len(r.content)
            written += 1
        if written:
            await db.commit()
        logger.info("[全书一致性修复] 改动章节 %s 个，%s", written, report.summary())
        for _n in report.notes:
            logger.warning("[全书一致性修复] %s", _n)
        return report


def _scope_scoped_context(full_context: str, scope: str) -> str:
    """按作用域裁剪【招标要求上下文】。

    技术/质量/进度等章节不需要看商务程序条款；全量广播只会让模型把
    "保证金账号""胶装份数""U盘"抄进技术方案里。商务/资格章节则要保留全文。
    """
    from services.generate.skills.bid_consistency import (
        PROCEDURAL_ALLOWED_SCOPES, strip_procedural_clauses,
    )
    if scope in PROCEDURAL_ALLOWED_SCOPES or not full_context:
        return full_context
    stripped, _ = strip_procedural_clauses(full_context)
    return stripped


def _scope_scoped_mandatory(mandatory: str, scope: str) -> str:
    """按作用域裁剪【废标红线】。非商务/资格章节只保留技术类红线。"""
    from services.generate.skills.bid_consistency import (
        PROCEDURAL_ALLOWED_SCOPES, strip_procedural_clauses,
    )
    if scope in PROCEDURAL_ALLOWED_SCOPES or not mandatory:
        return mandatory
    stripped, _ = strip_procedural_clauses(mandatory)
    # 全被剥掉了也要留个底，不能把红线整段丢掉
    return stripped if len(stripped.strip()) >= 200 else mandatory


async def _get_or_build_ledger(
    db: AsyncSession,
    outline: Outline | None,
    project,
    gateway,
    force: bool = False,
) -> dict | None:
    """取（或生成）全书统一口径台账，缓存在 outline.tree["commitments"]。

    为什么要缓存：台账是从招标文件提炼的一次性结果，全书共用；
    每章都重新提炼既慢又可能给出不同答案（那就等于没有统一口径）。

    注意：批量生成路径传进来的 outline/project 属于**已经关闭的 DI 会话**
    （端点在返回 StreamingResponse 前 await db.close()），是游离对象，其
    `tree` 快照可能是旧的。所以读缓存也要在传入的会话里按 id 重取一次实体，
    否则每次点"生成全文"都会重新跑一遍台账提炼。
    """
    target = None
    if outline is not None:
        try:
            row = await db.execute(select(Outline).where(Outline.id == outline.id))
            target = row.scalar_one_or_none()
        except Exception as e:
            logger.warning("[口径台账] 读取大纲失败: %s", e)
    source = target if target is not None else outline
    tree = source.tree if source is not None and isinstance(source.tree, dict) else None
    if tree is not None and not force:
        cached = tree.get("commitments")
        if isinstance(cached, dict) and (cached.get("items") or cached.get("key_params")):
            logger.info("[口径台账] 命中缓存: %s 项口径", len(cached.get("items") or []))
            return cached

    tender_doc_id = getattr(project, "tender_doc_id", None)
    project_id = getattr(project, "id", None)
    doc = None
    if tender_doc_id:
        doc_result = await db.execute(select(Document).where(Document.id == tender_doc_id))
        doc = doc_result.scalar_one_or_none()
    tender_text = doc.parsed_content if doc and doc.parsed_content else ""
    analysis = None
    if project_id:
        analysis_result = await db.execute(select(Analysis).where(Analysis.project_id == project_id))
        analysis = analysis_result.scalar_one_or_none()

    from services.generate.skills.commitment_ledger_skill import CommitmentLedgerSkill

    ctx = SkillContext(
        project_id=str(project_id or ""),
        db=db,
        llm=gateway,
        parameters={
            "tender_text": tender_text,
            "analysis_digest": _analysis_digest(analysis),
        },
    )
    result = await CommitmentLedgerSkill().safe_execute(ctx)
    if not result.success or not isinstance(result.data, dict):
        logger.warning("[口径台账] 生成失败(%s)，本次生成将不带全局口径约束", result.error)
        return None

    ledger = result.data
    if target is not None:
        try:
            tree_now = dict(target.tree) if isinstance(target.tree, dict) else {}
            tree_now["commitments"] = ledger
            target.tree = tree_now
            await db.flush()
        except Exception as e:
            logger.warning("[口径台账] 缓存失败: %s", e)

    logger.info("[口径台账] 已生成: %s 项口径 / %s 项参数",
                len(ledger.get("items") or []), len(ledger.get("key_params") or []))
    return ledger


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


def _format_project_facts(analysis: Analysis | None, ledger_text: str = "") -> str:
    """把解读结果里的项目基本信息整理成"全书唯一事实"块。

    全局事实层：全书**一次抽取**、**全量逐字注入每个小节的
    user 公共消息**（schema 只有 `{id,title,content}`），并且**缺失就直接
    拒绝启动正文生成**（「请先完成全局事实设定，再生成正文」）。

    我这里不需要再花一次模型调用：事实已经在解读结果 `analysis.dimensions`
    里，只是**从来没进过任何一章的 messages**（旧版只把 project_facts 用于
    事后一致性检查与封面）。后果实测：交付成稿里质保期有 6 种取值、工作阻力
    有 7 种取值 —— 因为正文生成时根本不知道这些口径。

    与台账的分工：
      · 台账（commitment_ledger）＝从招标文件提炼的**承诺口径**；
      · 本函数＝解读结果里的**项目基本事实**（名称/编号/采购人/工期…）。
    两者都是全书恒定，一起进 system，前缀缓存不受影响；重复项按值去重，
    避免同一件事出现两种说法。
    """
    facts = _extract_project_facts(analysis)
    if not facts:
        return ""
    # 常见键 → 中文标签；未知键原样输出（不猜、不改写）
    labels = {
        "project_name": "项目名称", "project_no": "项目编号", "project_code": "项目编号",
        "tender_no": "招标编号", "bid_no": "招标编号", "package_no": "标段/包号",
        "buyer": "采购人（招标人）", "purchaser": "采购人（招标人）",
        "tenderee": "采购人（招标人）", "agency": "招标代理机构",
        "budget": "采购预算", "budget_amount": "采购预算", "max_price": "最高限价",
        "bid_deadline": "投标截止时间", "deadline": "投标截止时间",
        "open_time": "开标时间", "bid_open_time": "开标时间",
        "deposit": "投标保证金", "bid_bond": "投标保证金",
        "validity": "投标有效期", "bid_validity": "投标有效期",
        "service_period": "服务期/工期", "duration": "工期/服务期", "delivery_period": "交货期",
        "warranty": "质保期", "quality_warranty": "质保期", "warranty_period": "质保期",
        "location": "项目地点", "project_location": "项目地点", "delivery_place": "交付地点",
        "copies": "投标文件份数", "bid_copies": "投标文件份数",
        "contact": "联系人", "contact_person": "联系人", "phone": "联系电话",
        "email": "电子邮箱", "bid_method": "投标方式", "evaluation_method": "评标办法",
        "qualification": "资格要求", "industry": "行业类别",
    }
    lines: list[str] = []
    for k, v in facts.items():
        val = str(v).strip()
        if not val or len(val) > 300:
            continue
        # 台账已经定过的口径不重复列，避免"同一件事两种说法"
        if ledger_text and val and val in ledger_text:
            continue
        lines.append(f"- {labels.get(str(k).lower(), k)}：{val}")
    if not lines:
        return ""
    return (
        "\n【项目基本事实 —— 全书唯一取值，不得写成别的】\n"
        + "\n".join(lines[:24])
        + "\n以上事实在全书任何章节都必须保持同一取值、同一单位、同一起算方式；"
        "\n不得改写、不得换算（例如写「90日历天」就不得写成「三个月」），"
        "不得补充未在此列出的编号、金额、日期、机构名称。"
    )


def _to_float_score(value) -> float:
    """宽容地把分值转成 float（可能是 10 / "10" / "10分" / None / "-"）。"""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"(\d+(?:\.\d+)?)", value)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return 0.0
    return 0.0


def _check_scoring_coverage_inline(
    tree: dict,
    contents: dict,
    score_items: list[dict] | None = None,
) -> dict | None:
    """评分项覆盖检查。

    旧实现有三个致命问题，全部用真实数据复现过：

    ① **拿到了权威映射却不用**：`score_mapping` 的值是大纲节点 id
       （"10" = 售后服务方案），但函数里 `for score_name, chapter_id in ...`
       只用了 `score_name`，`chapter_id` 拆包后从未被引用。于是检查退化成
       "这个评分项的名字在全书某处出现过吗"。
    ② **只看正文不看标题**：`contents` 是各章正文，不含标题。实测
       「质保措施及质保体系」「投标设备产品的运营可靠性」
       「投标设备产品质量保障措施」三项**明明各有一级专章**（id 8/6/7），
       却因为正文里没重复写这几个字而被判"未覆盖" —— 10 项里误报 3 项。
       反过来「售后服务」两个字在 92 章正文里都有，闭眼算覆盖。
    ③ **未映射的评分项凭空消失**：`total = len(score_mapping)`，只统计
       映射成功的项。某个评分项压根没被映射时，它既不算覆盖也不算缺失，
       覆盖率因此虚高。

    现在的判据分三层（由强到弱）：
      A 映射章节（含其全部下级章节）正文达到最小字数 → 有专章应答，覆盖；
      B 映射章节内出现评分项名/过半特征词 → 覆盖；
      C 其它章节明确出现该评分项名且特征词过半 → 覆盖（记在 detail 里说明）；
      都不满足才算缺失；未映射的项单独记为"未映射"并计入总数。
    """
    score_mapping = tree.get("score_mapping", {})
    if not isinstance(score_mapping, dict):
        score_mapping = {}

    items: list[dict] = []
    if isinstance(score_items, list) and score_items:
        for it in score_items:
            if isinstance(it, dict):
                nm = str(it.get("name") or "").strip()
                if nm:
                    items.append({"name": nm, "score": it.get("score") or 0})
            elif isinstance(it, str) and it.strip():
                items.append({"name": it.strip(), "score": 0})
    if not items:
        items = [{"name": str(k), "score": 0} for k in score_mapping]
    if not score_mapping and not items:
        return None

    contents = contents or {}

    def _subtree_text(node_id) -> str:
        """该大纲节点及其全部下级章节的正文。"""
        key = str(node_id or "")
        if not key:
            return ""
        parts = []
        for cid, txt in contents.items():
            scid = str(cid)
            if scid == key or scid.startswith(key + "."):
                if txt:
                    parts.append(txt)
        return "\n".join(parts)

    from services.generate.skills.outline_gen_skill import _tokenize_chinese

    full_text = "\n".join(v for v in contents.values() if v)

    covered = 0
    covered_score = 0.0
    total_score = 0.0
    missing_items: list[str] = []
    detail: list[dict] = []

    for item in items:
        name = item["name"]
        total_score += _to_float_score(item.get("score"))

        node_id = ""
        for key, val in score_mapping.items():
            if str(key).strip() == name:
                node_id = str(val or "")
                break

        if not node_id:
            missing_items.append(name)
            detail.append({"item": name, "status": "未映射",
                           "note": "大纲阶段没有为这一项匹配到章节"})
            continue

        own = _subtree_text(node_id)
        hit_own = bool(own) and len(own) >= MIN_CHAPTER_WORDS
        reason = "专章应答" if hit_own else ""

        if not hit_own:
            if name and name in own:
                hit_own, reason = True, "章节内命中评分项名"
        if not hit_own:
            tokens = _tokenize_chinese(name)
            if tokens:
                hit = sum(1 for t in tokens if t in own)
                if hit / len(tokens) >= 0.5:
                    hit_own, reason = True, "章节内特征词过半"

        if not hit_own:
            # 可能应答写在别的章里：只有"名字明确出现 + 特征词过半"才算，
            # 避免"售后服务"这种高频词在 92 章里都算覆盖
            tokens = _tokenize_chinese(name)
            elsewhere = bool(name) and name in full_text and bool(tokens) and (
                sum(1 for t in tokens if t in full_text) / len(tokens) >= 0.5
            )
            if elsewhere:
                hit_own, reason = True, "在其它章节响应"

        if hit_own:
            covered += 1
            covered_score += _to_float_score(item.get("score"))
            detail.append({"item": name, "status": "已覆盖", "chapter": node_id,
                           "reason": reason, "words": len(own)})
        else:
            missing_items.append(name)
            detail.append({"item": name, "status": "缺失", "chapter": node_id,
                           "note": "对应章节正文过短且未提该项", "words": len(own)})

    total = len(items)
    if total == 0:
        return None

    report = {
        "total": total,
        "covered": covered,
        "missing_count": len(missing_items),
        "coverage_rate": round(covered / total * 100, 1),
        "missing_items": missing_items[:10],
        "detail": detail,
        "via_mapping": sum(1 for d in detail if d.get("chapter")),
    }
    if total_score > 0:
        report["total_score"] = round(total_score, 1)
        report["covered_score"] = round(covered_score, 1)
        report["score_coverage_rate"] = round(covered_score / total_score * 100, 1)
    return report


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


def _post_process_stream_content(
    content: str,
    chapter_title: str,
    is_overview: bool = False,
    protect_names: tuple[str, ...] = (),
) -> str:
    """正文清洗。

    is_overview=True（分支章的"本章概述"）时跳过元语言剥离：概述的职责就是交代
    "本章写什么、下级由谁展开"，天然会出现"本章主要…""本章系统…"这类措辞，而它们
    正在元语言清单里 → 整句被删。实测 266 字的概述被删到 92 字，低于有效正文门槛，
    等于整章丢失（导出时那一章近乎空白）。

    protect_names：企业/项目名称，禁止被重复词规则折叠。清洗器的重复词规则是
    `([\\u4e00-\\u9fff]{3,4})\\1 -> \\1`，它会把含叠字的企业名改坏，而正文公司名
    与营业执照不一致属于实质性偏差 —— 保护起来，宁可漏清洗。
    """
    from services.generate.skills.content_cleaner import clean_generated_content
    return clean_generated_content(
        content, chapter_title, protect_names, skip_meta_strip=is_overview
    )


def _failed_markers_in(content: str) -> list[str]:
    """正文里出现"生成失败"痕迹时返回命中词，否则返回空列表。

    用途：拦住 `_fallback_overview` / `_generate_data_placeholder` 的产物入库。
    这类文本（"【本章正文未能生成】…"）一旦落库，导出时会原样出现在正式投标
    文件里 —— 等于直接告诉评委"这章我们没写"。
    """
    if not content:
        return ["正文为空"]
    try:
        from services.generate.skills.norm_rules import find_failed_markers
        return find_failed_markers(content)
    except Exception:
        return []


def _protect_names_for(analysis: Analysis | None, project=None) -> tuple[str, ...]:
    """收集投标人/采购人/项目名称，交给清洗器做"禁止折叠"保护。

    原因：清洗器的重复词规则会把"山西一一科技"这类含叠字的企业名改坏，
    而正文里的公司名与营业执照不一致属于实质性偏差。
    """
    names: list[str] = []
    if project is not None and getattr(project, "name", None):
        names.append(str(project.name))
    dims = analysis.dimensions if (analysis and isinstance(analysis.dimensions, dict)) else {}
    for key in ("project_info", "buyer_info"):
        val = dims.get(key)
        if not isinstance(val, dict):
            continue
        for field in ("project_name", "name", "buyer_name", "tenderer", "purchaser",
                      "招标人", "采购人", "项目名称", "投标人", "company_name"):
            v = val.get(field)
            if isinstance(v, str) and len(v.strip()) >= 4:
                names.append(v.strip())
    seen: set[str] = set()
    return tuple(n for n in names if not (n in seen or seen.add(n)))


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
    # 选中的节点如果有下级章节，是否连带把它的子孙章节一并生成。
    # 用户要求："选 1.1 时把 1.1.X 下面的一起生成，选 1 时把 1.X 下面的一起生成"。
    include_children: bool = True,
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

    # ── 连带子章节：把"选中的节点"展开成"它自己 + 全部后代" ──────────────
    # 以前这里只生成选中的那一个节点。用户选 1.1 时，1.1.1/1.1.2… 仍然要一个一个点，
    # 实战中一本书要手动点几百次。现在选父节点就等于选它整棵子树。
    targets: list[dict] = []
    if chapter_node is not None:
        targets = _subtree_infos(chapter_node)
    elif chapter and chapters_list:
        # 用数据库 id 进来的：按标题在大纲里找对应的节点，仍尽量展开子树
        found = None
        for n in chapters_list:
            if isinstance(n, dict) and n.get("title") == chapter_title:
                found = n
                break
        if found is not None:
            chapter_node = found
            targets = _subtree_infos(found)
    if not targets:
        targets = [{
            "id": chapter_id, "title": chapter_title, "parent_id": "",
            "parent_title": "", "is_parent": bool(chapter_node and chapter_node.get("children")),
        }]

    if not include_children:
        targets = targets[:1]

    _subtree_max = max(1, int(os.getenv("BMP_SUBTREE_MAX", "60")))
    truncated = len(targets) > _subtree_max
    if truncated:
        logger.info("[单章生成] 子树 %s 个节点超过上限 %s，只生成前 %s 个",
                    len(targets), _subtree_max, _subtree_max)
        targets = targets[:_subtree_max]

    # sort_order 必须按**全量大纲**的深度优先序号算，否则同名节点会互相覆盖
    all_infos = _collect_chapter_ids(chapters_list) if chapters_list else []
    node_order = {c["id"]: i + 1 for i, c in enumerate(all_infos)}

    doc_result = await db.execute(
        select(Document).where(Document.id == project.tender_doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    tender_context = _build_tender_context(doc.parsed_content) if doc and doc.parsed_content else ""

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    mandatory_reqs = _extract_mandatory_requirements(analysis)

    # ── 把"已经写好的其它章节正文"读回来，供本章做承接与去重 ──
    # 旧版单章路径完全不回灌（审计⑥），所以用户点"重新生成本章"必然孤立、
    # 越修越不通顺。chapters 表没有大纲节点 id 列，落库时是按全量深度优先
    # 序号（sort_order）认领的（见 _persist_chapter_now），这里按同一口径反查。
    prior_contents: dict[str, str] = {}
    try:
        _id_by_order = {i + 1: c["id"] for i, c in enumerate(all_infos)}
        _id_by_title: dict[str, str] = {}
        for _c in all_infos:
            _id_by_title.setdefault(str(_c.get("title") or ""), str(_c.get("id") or ""))
        _rows = await db.execute(
            select(Chapter).where(Chapter.project_id == project_id)
        )
        for _rec in _rows.scalars().all():
            _cid = _id_by_order.get(int(_rec.sort_order or 0)) or \
                _id_by_title.get(str(_rec.title or ""))
            _body = (_rec.content or "").strip()
            # 失败/占位内容不参与承接（门槛与批量路径一致）
            if _cid and _cid != ch_id and len(_body) >= 100 and not _failed_markers_in(_body):
                prior_contents[_cid] = _body
        if prior_contents:
            logger.info("[单章生成] 已回灌 %d 章已写正文供承接去重", len(prior_contents))
    except Exception as _pe:
        logger.warning("[单章生成] 读取已写章节失败（不影响本章生成）: %s", _pe)

    # 全局口径台账：单章生成也要带（否则单章重生成会写出与全书不一致的数字）
    ledger = await _get_or_build_ledger(db, outline, project, get_llm_gateway())
    ledger_text = _format_ledger(ledger)
    # 项目基本事实：单章重生成同样要带，否则它会写出与全书不同的编号/名称/工期
    project_facts_text = ""
    try:
        project_facts_text = _format_project_facts(analysis, ledger_text)
    except Exception as _fe:
        logger.warning("[单章生成] 项目基本事实构造失败: %s", _fe)
    # 企业/项目名称保护：禁止被清洗器的重复词规则折叠（名称与营业执照不一致=废标）
    protect_names = _protect_names_for(analysis, project)
    if ledger is not None:
        # 台账缓存写在 outline.tree 上，必须显式提交：本端点随后会 db.close()，
        # 未提交的事务会被回滚，下次又要重新提炼一遍。
        try:
            await db.commit()
        except Exception as _ce:
            logger.warning("[口径台账] 提交缓存失败: %s", _ce)

    # 按标的物切分的技术规格（同样要提交，理由同上）
    _raw_tender = doc.parsed_content if doc and doc.parsed_content else ""
    specs = await _get_or_build_specs(db, outline, _raw_tender, get_llm_gateway())
    if specs:
        try:
            await db.commit()
        except Exception as _ce:
            logger.warning("[设备规格] 提交缓存失败: %s", _ce)
    repair_ctx = _build_repair_ctx(_raw_tender, ledger, specs)

    gateway = get_llm_gateway()
    outline_id = outline.id if outline else None
    root_id = targets[0]["id"]
    root_title = targets[0]["title"] or chapter_title

    async def event_generator():
        q: asyncio.Queue = asyncio.Queue(maxsize=4000)
        streamed_any = {"root": False}

        async def _run() -> None:
            failed_children: list[dict] = []
            root_words = 0
            try:
                for idx, info in enumerate(targets, start=1):
                    ch_id = info["id"]
                    ch_title = info["title"] or ch_id
                    is_root = (ch_id == root_id)
                    is_branch = bool(info.get("is_parent"))
                    if is_branch:
                        chapter_words = OVERVIEW_WORDS
                    else:
                        chapter_words = resolve_chapter_words(word_count, ch_title)

                    q.put_nowait({"type": "chapter_start", "chapter_id": ch_id,
                                  "chapter_title": ch_title, "index": idx,
                                  "total": len(targets), "is_root": is_root})

                    async def _on_chunk(text: str, _root=is_root):
                        # 只把"根章节"的增量文本往前端推：前端单章编辑器会把
                        # content 直接追加到当前章节的文本框里，子章节的文本混进来
                        # 就会把父章节的正文写错。
                        if _root:
                            streamed_any["root"] = True
                            q.put_nowait({"content": text})

                    status, rid, rtitle, payload = await _generate_one_chapter(
                        project_id=project_id,
                        ch_id=ch_id,
                        ch_title=ch_title,
                        chapters_list=chapters_list,
                        tree=tree,
                        tender_context=tender_context,
                        mandatory_reqs=mandatory_reqs,
                        ledger_text=ledger_text,
                        mode=mode,
                        chapter_words=chapter_words,
                        is_branch=is_branch,
                        gateway=gateway,
                        on_chunk=_on_chunk,
                        repair_ctx=repair_ctx,
                        # 单章重生成也要"看得到"已写好的章节：否则用户
                        # 点"重新生成本章"必然是孤立的，越修越不通顺。
                        all_contents=prior_contents,
                        project_facts_text=project_facts_text,
                        protect_names=protect_names,
                    )
                    seq = node_order.get(ch_id, 0)

                    if status == "ok":
                        try:
                            await _persist_chapter_now(
                                outline_id, project_id, ch_id, ch_title,
                                payload, mode, seq, "generated",
                            )
                        except Exception as _pe:
                            logger.warning("[单章生成] 落库失败 chapter=%s: %s", ch_title, _pe)
                        if is_root:
                            root_words = len(payload)
                        q.put_nowait({"type": "chapter_done", "chapter_id": ch_id,
                                      "chapter_title": ch_title, "word_count": len(payload),
                                      "completed": idx, "total": len(targets)})
                    else:
                        if not is_root:
                            failed_children.append({"id": ch_id, "title": ch_title,
                                                    "error": str(payload)[:300]})
                        try:
                            await _persist_chapter_now(
                                outline_id, project_id, ch_id, ch_title,
                                _fallback_overview(ch_title), mode, seq, "failed",
                                preserve_existing=True,
                            )
                        except Exception as _pe:
                            logger.warning("[单章生成] 失败章节落库失败 chapter=%s: %s", ch_title, _pe)
                        # 注意：单章流里**不能**出现 error 键，前端见到 je.error 会立刻
                        # 取消整个流。子章节的失败只放进最终的 done 事件里。
                        q.put_nowait({"type": "chapter_error", "chapter_id": ch_id,
                                      "chapter_title": ch_title, "error_text": str(payload)[:200],
                                      "is_root": is_root})
                        if is_root and not failed_children:
                            q.put_nowait({"error": f"「{ch_title}」生成失败：{str(payload)[:200]}",
                                          "blocked": [str(payload)[:200]]})
                            return

                if failed_children:
                    q.put_nowait({"type": "partial_failure", "failed_chapters": failed_children,
                                  "failed": len(failed_children),
                                  "generated": len(targets) - len(failed_children)})
                q.put_nowait({"done": True, "word_count": root_words,
                              "generated": len(targets) - len(failed_children),
                              "failed": len(failed_children),
                              "failed_chapters": failed_children,
                              "truncated": truncated})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("[单章生成] 异常: %s", e)
                q.put_nowait({"error": str(e)})
            finally:
                q.put_nowait(None)

        task = asyncio.create_task(_run())
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            # 客户端断开时不取消 _run：每一章都会即时落库，让它跑完不浪费，
            # 也避免"点了生成又切页面"导致章节静默缺失。
            pass

    # 生成器内部自带独立会话，这里提前归还 DI 会话的连接
    await db.close()
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )




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


# ══════════════════════════════════════════════════════════════════════════
# 批量生成：与 HTTP 连接解耦 + 每章即时落库
# ══════════════════════════════════════════════════════════════════════════
# 旧实现把生成逻辑写在 SSE 生成器里、落库放在全部章节跑完之后，于是有两个后果：
#   1) 关掉浏览器/刷新页面 → Starlette 取消响应生成器 → 生成中断，而且
#      **前面几十分钟生成的正文全部丢失**（持久化那段代码压根没执行到）。
#   2) 最后一章之后任何一步抛异常（口径体检、一致性检查…）同样前功尽弃。
# 现在：真正的生成跑在独立的 asyncio 任务里，每章一完成立刻单独提交事务；
# SSE 只负责订阅事件广播。客户端断开只是少一个订阅者，任务继续跑。
#
# 关于"停止"：前端"停止批量生成"只是 abort 掉 fetch，服务端收不到停止信号。
# 所以这里用"没有任何订阅者且持续超过 BMP_GEN_DETACH_GRACE 秒"作为兜底停止条件，
# 避免一个卡死的任务无限期占用 LLM 配额；也可以用 POST .../content/stop 显式停。
_BATCH_RUNS: dict[str, "_BatchRun"] = {}
_BATCH_RUNS_LOCK = asyncio.Lock()
# 单章/子树的生成任务。客户端断开后不取消它们（每章都即时落库），
# 这里持引用防止任务被垃圾回收。
_BG_TASKS: set[asyncio.Task] = set()


class _BatchRun:
    """一次批量生成运行的状态与事件广播中心。"""

    def __init__(self, project_id: str, total: int, only_missing: bool = False):
        self.project_id = project_id
        self.total = total
        self.only_missing = only_missing
        self.completed = 0
        self.failed = 0
        self.failed_chapters: list[dict] = []
        self.done_chapters: list[dict] = []
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.error: str | None = None
        self.stopped_by_detach = False
        # ② 独立心跳协程（见 _gen_lock_heartbeat）。运行标记不再只依赖章节边界，
        #    慢章节（429 重试链可达数分钟）不会再让运行标记被误判为过期。
        self.heartbeat_task = None
        # 项目被删除导致的外键失败会让整批"生成成功但存不进去"，
        # 命中即中止，用这个标记区分"中止"与"跑完"。
        self.aborted = False
        self.task: asyncio.Task | None = None
        self.history: list[dict] = []
        self._subs: set[asyncio.Queue] = set()
        self.last_subscriber_gone: float | None = None

    # ── 事件广播 ──────────────────────────────────────────────
    def emit(self, event: dict) -> None:
        self.history.append(event)
        if len(self.history) > 4000:
            del self.history[:1500]
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 订阅者跟不上了，丢弃该订阅者而不是拖慢生成
                self._subs.discard(q)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._subs.add(q)
        self.last_subscriber_gone = None
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)
        if not self._subs:
            self.last_subscriber_gone = time.time()

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def detach_expired(self, grace: float) -> bool:
        if self._subs or self.last_subscriber_gone is None:
            return False
        return (time.time() - self.last_subscriber_gone) > grace

    def payload(self) -> dict:
        return {
            "project_id": self.project_id,
            "running": not self.finished,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "only_missing": self.only_missing,
            "failed_chapters": self.failed_chapters[-80:],
            "started_at": self.started_at,
            "elapsed_seconds": round((self.finished_at or time.time()) - self.started_at, 1),
            "subscribers": self.subscriber_count,
            "error": self.error,
            "stopped_by_detach": self.stopped_by_detach,
        }


def _detach_grace_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("BMP_GEN_DETACH_GRACE", "1800")))
    except Exception:
        return 1800.0


def _find_node(nodes: list, target_id: str) -> dict | None:
    """在大纲树里按 id 找节点。"""
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        if n.get("id") == target_id:
            return n
        found = _find_node(n.get("children") or [], target_id)
        if found is not None:
            return found
    return None


def _subtree_infos(node: dict, parent: dict | None = None) -> list[dict]:
    """目标节点 + 其全部后代（深度优先），用于"生成父章节时连带生成子孙"。"""
    infos = [{
        "id": node.get("id", ""),
        "title": node.get("title", ""),
        "parent_id": parent.get("id", "") if parent else "",
        "parent_title": parent.get("title", "") if parent else "",
        "is_parent": bool(node.get("children")),
    }]
    for child in node.get("children") or []:
        if isinstance(child, dict):
            infos.extend(_subtree_infos(child, node))
    return infos


def _is_project_gone(exc: BaseException) -> bool:
    """判断异常是否为"项目已被删除"（外键 chapters_project_id_fkey 违反）。

    实测事故：用户在批量生成进行到一半时删掉项目并新建了一个项目，旧任务
    却继续为剩余章节调用模型 —— 每一章都抛外键错误、内容全部丢弃，模型配额
    白烧（日志里连续 88 条"落库失败 ... is not present in table projects"）。
    命中此判据就应当中止整批，而不是继续跑。
    """
    s = str(exc)
    if "chapters_project_id_fkey" in s:
        return True
    return (
        "ForeignKeyViolationError" in s
        and "project_id" in s
        and "projects" in s
    )


async def _persist_chapter_now(
    outline_id: str | None,
    project_id: str,
    ch_id: str,
    ch_title: str,
    content: str,
    mode: str,
    sort_order: int = 0,
    status: str = "generated",
    preserve_existing: bool = False,
) -> None:
    """把一章正文立刻写库并提交。

    独立会话 + 立即提交是有意为之：这是"关掉浏览器不丢内容"的关键。
    失败章节也照样落库（内容为显式占位、status=failed），这样
    ①前端"重新生成未加载内容（N 章）"能把它数进去并重跑；
    ②导出门禁能把它识别为硬伤而不是当成"没有这一章"。

    preserve_existing=True：本次失败但库里已有像样的正文时，**保留原文**
    只改 status（重跑失败不该把上次生成好的内容抹掉）。
    """
    from services.database import async_session
    factory = async_session()
    async with factory() as db:
        conds = [Chapter.project_id == project_id]
        if outline_id:
            conds.append(Chapter.outline_id == outline_id)

        rec = None
        if sort_order:
            r = await db.execute(
                select(Chapter).where(*conds, Chapter.sort_order == sort_order)
            )
            rec = r.scalar_one_or_none()
        if rec is None and ch_title:
            # 兼容历史数据(sort_order 全为 0)：按标题认领还没被认领的那条
            r = await db.execute(
                select(Chapter)
                .where(*conds, Chapter.title == ch_title, Chapter.sort_order == 0)
                .order_by(Chapter.created_at)
            )
            rec = r.scalars().first()

        if rec is not None:
            old = (rec.content or "").strip()
            if preserve_existing and len(old) >= 100 and not _failed_markers_in(old):
                # 保留上次的好内容，只标记状态
                rec.status = status
            else:
                rec.content = content
                rec.mode = mode
                rec.status = status
                rec.word_count = len(content)
            if sort_order:
                rec.sort_order = sort_order
        else:
            db.add(Chapter(
                project_id=project_id,
                outline_id=outline_id,
                title=ch_title or ch_id,
                content=content,
                mode=mode,
                status=status,
                word_count=len(content),
                sort_order=sort_order,
            ))
        await db.commit()


# ── 跨进程运行标记（api 是 uvicorn --workers 2，内存表不跨进程）──────────
def _gen_lock_path(project_id: str) -> Path:
    root = Path(os.getenv("BMP_PROJECTS_ROOT", "./projects"))
    return root / str(project_id) / ".stages" / "generate" / ".running.json"


def _write_gen_lock(project_id: str, state: dict) -> None:
    p = _gen_lock_path(project_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(state)
        payload["heartbeat"] = time.time()
        payload["pid"] = os.getpid()
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("[批量生成] 写运行标记失败: %s", e)


def _read_gen_lock(project_id: str) -> dict | None:
    p = _gen_lock_path(project_id)
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    try:
        if time.time() - float(data.get("heartbeat", 0)) > 240:
            return None  # 心跳过期，视为进程已死
    except Exception:
        return None
    return data


def _clear_gen_lock(project_id: str) -> None:
    try:
        p = _gen_lock_path(project_id)
        if p.exists():
            p.unlink()
    except Exception:
        pass


async def _gen_lock_heartbeat(project_id: str, run) -> None:
    """独立心跳：每 30 秒续写一次运行标记，与"章节边界"和"订阅者"都无关。

    为什么必须有它：原来运行标记只在每章开始/结束时写（见 _batch_worker），
    而 _read_gen_lock 以 **240 秒**为过期阈值。上游限流（429）时单章的重试链是
    "3 次 × 20 秒 + 流式等待"，实测可以超过 240 秒 —— 这段时间运行标记看起来
    "心跳过期、进程已死"，于是另一次点击/另一个 worker 就会走 `新建任务` 分支，
    同一个项目出现两份并行生成（也就是"刷新页面后按钮又可点，点下去就多一个任务"）。
    心跳改成定时续写后，只要任务真的还活着，标记就不会被误判为过期。

    写之前先判 finished/task.done()：避免 worker 收尾时已 _clear_gen_lock，
    心跳又把它重新创建出来，留下一个"看起来还活着"的假标记。
    """
    try:
        while True:
            await asyncio.sleep(30)
            if run.finished or (getattr(run, "task", None) is not None
                                and run.task.done()):
                break
            _write_gen_lock(project_id, {
                "total": run.total,
                "completed": run.completed,
                "failed": run.failed,
            })
    except asyncio.CancelledError:
        pass
    except Exception as e:  # 心跳失败绝不能影响生成
        logger.warning("[批量生成] 运行标记心跳异常（已忽略）: %s", e)


async def _mirror_other_run(project_id: str, lock: dict):
    """另一个 worker 正在跑：只做只读进度订阅，避免同一项目跑两份生成。"""
    total = int(lock.get("total") or 0)
    yield f"data: {json.dumps({'type': 'start', 'total': total, 'mirrored': True}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'type': 'stage', 'stage': 'mirror', 'message': '该项目已在后台生成中，正在同步进度...'}, ensure_ascii=False)}\n\n"
    last = None
    while True:
        cur = _read_gen_lock(project_id)
        if cur is None:
            yield f"data: {json.dumps({'type': 'done', 'total': total, 'completed': int(lock.get('completed') or 0), 'failed': int(lock.get('failed') or 0), 'mirrored': True}, ensure_ascii=False)}\n\n"
            return
        snapshot = (cur.get("completed"), cur.get("failed"), cur.get("total"))
        if snapshot != last:
            last = snapshot
            yield f"data: {json.dumps({'type': 'progress', 'current': int(cur.get('completed') or 0) + int(cur.get('failed') or 0), 'completed': int(cur.get('completed') or 0), 'failed': int(cur.get('failed') or 0), 'total': int(cur.get('total') or total), 'chapter_title': '（后台生成中）'}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(5)


_SENT_TAIL = ("。", "！", "？", "；", "：", "”", "）", "…", ".", "!", "?", ";", "|", "`")


def _trim_overlap(base: str, add: str, max_overlap: int = 240) -> str:
    """续写文本与已有正文的重复接头去掉。

    模型"接着写"时习惯把上一句重新抄一遍再往下写。直接拼接会出现
    "……保证支护强度。保证支护强度。本公司……"这种重复。这里在 base 的末尾
    与 add 的开头之间找最长重叠（8~240 字），找到就只取重叠之后的部分。
    """
    if not base or not add:
        return add
    tail = base.rstrip()
    n = min(len(tail), len(add), max_overlap)
    # 下界必须 <= 6：续写常常只回传"上一句 + 新内容"，overlap 可能只有几个字。
    # 之前写成 range(n, 7, -1)，当 n<=7 时是空循环 —— 短续写的接头永远去不掉。
    # 取 6 字而非更短，是为了避免把模型正常起句的"本公司"这类词误当接头删掉。
    for k in range(n, 5, -1):
        if add[:k] == tail[-k:]:
            return add[k:]
    return add


async def _continue_if_truncated(
    *,
    gateway,
    msgs: list,
    content: str,
    ch_title: str,
    target_words: int,
    max_tokens: int,
    finish_reason: str,
    on_chunk=None,
    max_rounds: int = 2,
    protect_names: tuple[str, ...] = (),
) -> str:
    """被 max_tokens 截断时带着已写内容继续写，直到写完或不再增长。

    为什么必须做：旧实现只处理"整章不足 50 字"的空流，而 max_tokens 被写满时
    正文往往已有一两千字、远大于 50 —— 于是判成功入库。导出到 Word 就是一句
    写了一半的话，评委一眼可见，属于实质性缺陷。

    判据（宁可少续不可乱续）：
      ① finish_reason == "length"：provider 明确表示被长度截断，最强信号；
      ② 正文不足目标字数的 70% 且结尾不是句末标点：明显写一半停了。
    只有明确截断、或"又短又没写完"才续写，正常写短的章节不会被强行拉长。

    续写手法与网关内部"流式中断重试"完全一致：把已写内容作为 assistant 消息
    回灌，再让模型接着写 —— 这也是 assistant 前缀机制。

    流式一致性：续写**不逐块推给前端**，而是拼好、去掉重复接头之后整段推送。
    因为前端累积的正文必须与入库正文逐字一致，否则用户再点保存就把差异写回去。
    """
    if not content or len(content.strip()) < 50:
        return content

    truncated = finish_reason == "length"
    tail = content.rstrip()[-1:] if content.rstrip() else ""
    looks_unfinished = bool(tail) and tail not in _SENT_TAIL
    if not truncated and not (looks_unfinished and len(content) < int(target_words * 0.7)):
        return content

    logger.info(
        "[正文生成] 检测到未写完 chapter=%s finish_reason=%s 现有%d字 目标%d字 结尾=%r",
        ch_title, finish_reason or "(未知)", len(content), target_words, tail,
    )

    out = content
    _last_fr = finish_reason
    for rnd in range(max_rounds):
        try:
            cont_msgs = msgs + [
                {"role": "assistant", "content": out[-1500:]},
                {"role": "user", "content": (
                    "上面是你刚写的正文末尾。请**紧接着**继续写下去：从被中断的"
                    "那句话继续，保持相同的语言风格、层级结构和编号体例。"
                    "不要重复已经写过的任何句子或段落，不要重新输出标题，"
                    "不要写任何说明性文字，直接接着写正文。"
                )},
            ]
            chunks: list[str] = []
            _cmeta: dict = {}
            async for c in gateway.stream_chat(
                messages=cont_msgs, temperature=0.7,
                max_tokens=max_tokens, no_thinking=True, meta=_cmeta,
            ):
                chunks.append(c)
            _last_fr = str(_cmeta.get("finish_reason") or "")
            raw_add = "".join(chunks)
            if not raw_add.strip():
                break
            add = _trim_overlap(out, _post_process_stream_content(raw_add, ch_title, protect_names=protect_names))
            if not add.strip() or len(add.strip()) < 20:
                logger.info("[正文生成] 续写无有效增量，停止 chapter=%s", ch_title)
                break
            out = out.rstrip() + "\n" + add.lstrip()
            if on_chunk is not None:
                try:
                    # 只把"净增量"推给前端，保证前端缓冲 == 入库正文
                    await on_chunk("\n" + add.lstrip())
                except Exception:
                    pass
            logger.info(
                "[正文生成] 续写第%d轮 chapter=%s 增量%d字 合计%d字",
                rnd + 1, ch_title, len(add), len(out),
            )
            if len(out) >= int(target_words * 0.9):
                break
        except Exception as e:
            logger.warning("[正文生成] 续写失败 chapter=%s: %s", ch_title, e)
            break
    if _last_fr == "length":
        # 对标项目的做法是"截断即作废、整节重试"（reject_truncated_output）。
        # 这里不采用"作废"：作废会丢掉已经写好的正文，违反本项目
        # "宁可漏改不可错改、绝不为软问题丢内容"的红线。改为保留正文 + 明确告警，
        # 让运维/用户能看到哪一章需要重新生成。
        logger.warning(
            "[正文生成] 续写 %d 轮后仍被截断 chapter=%s 最终%d字 目标%d字 "
            "—— 已保留现有正文（不丢内容），建议对该章单独重新生成",
            max_rounds, ch_title, len(out), target_words,
        )
    return out


async def _generate_one_chapter(
    *,
    project_id: str,
    ch_id: str,
    ch_title: str,
    chapters_list: list,
    tree: dict,
    tender_context: str,
    mandatory_reqs: str,
    ledger_text: str,
    mode: str,
    chapter_words: int,
    is_branch: bool,
    gateway,
    on_chunk=None,
    repair_ctx: dict | None = None,
    all_contents: dict | None = None,
    project_facts_text: str = "",
    protect_names: tuple[str, ...] = (),
) -> tuple[str, str, str, str]:
    """生成单章正文（批量路径与单章路径共用）。

    on_chunk: 可选的 async 回调，收到每个增量文本片段时调用一次。
              批量路径不传（省掉无谓的调度）；单章路径传进来做"打字机"效果。

    返回 (status, ch_id, ch_title, payload)：
        ("ok",     id, title, 正文)
        ("failed", id, title, 失败原因)   —— 内容里带失败痕迹，不该当成功
        ("error",  id, title, 异常信息)
    """
    try:
        chapter_node, parent_node, sibling_nodes = _find_outline_node_with_context(
            chapters_list, ch_id
        )
        chapter_context = _build_chapter_context_text(
            chapter_node, parent_node, sibling_nodes, ch_id
        )
        scoring_context = _build_scoring_context(tree, ch_id, chapter_node)
        chapter_outline = _describe_node_tree(chapter_node) if chapter_node else ""

        # ── 内容形态（第三层）：优先用大纲里已标注的 content_mode ──
        # classify_tree 生成大纲时已原地写入并整树落库；老项目/未标注的走标题兜底。
        # 兜底很重要：报价、投标函这类章节即使没被标注，也绝不能让模型自由发挥。
        try:
            from services.generate.skills.chapter_attrs import (
                CONTENT_MODES as _CMS, classify_title, enforce_content_mode,
            )
            _cm = str((chapter_node or {}).get("content_mode") or "").strip()
            if _cm not in _CMS:
                _attr = str((chapter_node or {}).get("attr") or "").strip() \
                    or classify_title(ch_title)
                _cm = enforce_content_mode(_attr)
            if _cm not in _CMS:
                _cm = "ai-generate"
        except Exception as _cme:
            logger.warning("[正文生成] 内容形态判定失败，按 ai-generate 处理: %s", _cme)
            _cm = "ai-generate"
        if is_branch:
            # 分支节点只写"本章概述"，形态约束交给下级章节各自承担
            _cm = "ai-generate"

        system_prompt = build_chapter_system_prompt(
            ch_title, chapter_words, overview=is_branch, ledger_text=ledger_text,
            stable=True, project_facts_text=project_facts_text, content_mode=_cm,
        )

        # 先把本章归到某个作用域与某几台设备，再据此裁剪注入内容
        from services.generate.skills.bid_consistency import classify_scope
        from services.generate.skills.tender_specs import (
            detect_chapter_devices, render_all_specs_table, render_spec_block,
        )
        _scope = classify_scope(ch_title)
        _specs = (repair_ctx or {}).get("specs") or {}
        _devs = detect_chapter_devices(ch_title, "", _specs) if _specs else []

        msgs = [{"role": "system", "content": system_prompt}]
        if tender_context:
            msgs.append({
                "role": "user",
                "content": "【招标要求上下文】\n" + _scope_scoped_context(tender_context, _scope),
            })
        if chapter_context:
            msgs.append({"role": "user", "content": chapter_context})
        if scoring_context:
            msgs.append({"role": "user", "content": scoring_context})
        # 设备参数锁定：讲哪台设备就只给它那一台的真实参数表，杜绝张冠李戴
        if _specs:
            _blocks: list[str] = []
            for _d in _devs:
                if _d in _specs:
                    _blocks.append(render_spec_block(_d, _specs[_d]))
            if not _blocks:
                # 本章不针对某一台设备（总述/通用方案）→ 给横向对标总表，
                # 并明确要求"只写本章涉及设备的参数"，不许把别的设备参数搬过来
                _tbl = render_all_specs_table(_specs)
                if _tbl:
                    _blocks.append(
                        "【全书设备技术参数总表 —— 招标文件原文】\n" + _tbl
                        + "\n注意：本章若不针对某一台设备，就不要给出任何具体设备参数；"
                          "确需对比时，每一台设备的数值必须与本表一一对应，严禁交叉引用。"
                    )
            if _blocks:
                msgs.append({
                    "role": "system",
                    "content": "【标的物技术参数锁定 —— 最高优先级，高于你的任何推断】\n"
                               + "\n\n".join(_blocks)
                               + "\n凡涉及上述参数的表述，数值与单位必须与上表完全一致；"
                                 "上表未给出的参数，写成 {{待填:参数名称}} 占位，"
                                 "严禁自行推算、补充或与其它标的物混用。",
                })
        if mandatory_reqs:
            # 废标红线用 system 角色、预算提到 12000 字（招标文件里单条实质性
            # 要求实测就有 6000+ 字，截到 2000 等于丢掉大半红线）
            msgs.append({
                "role": "system",
                "content": (
                    "【废标红线 / 实质性要求 —— 必须逐条实质性响应，缺一条即可能被判无效投标】\n"
                    + _scope_scoped_mandatory(mandatory_reqs, _scope)[:12000]
                    + "\n请在正文中对上述每一条给出可被评委直接核对的响应内容"
                      "（承诺、措施、数量、时限、附件名称），不得只写口号。"
                ),
            })
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
                            msgs.append({
                                "role": "user",
                                "content": f"【参考材料（请优先引用其中的具体数据和案例）】\n{rc[:6000]}",
                            })
                except Exception as e:
                    logger.warning(f"[正文生成] RAG检索失败(chapter={ch_id}): {e}")

        # 【已写章节 —— 承接与去重依据】必须放在本章任务之前：变化内容集中在
        # 消息尾部，前面逐字稳定的前缀缓存不受影响。
        _prior = ""
        if all_contents:
            try:
                _prior = build_prior_context_block(ch_id, chapters_list, all_contents)
            except Exception as _e:
                logger.warning("[正文生成] 构造已写章节摘要失败 chapter=%s: %s", ch_id, _e)
        if _prior:
            msgs.append({"role": "user", "content": _prior})

        # 编排阶段的产物：本节写作重点 + 全书位置（writing_focus / chapter_path）。
        _focus = str((chapter_node or {}).get("writing_focus") or "")
        _path = ""
        try:
            from services.generate.skills.content_plan_skill import node_path
            _path = node_path(chapters_list, ch_id)
        except Exception as _e:
            logger.warning("[正文生成] 计算章节路径失败 chapter=%s: %s", ch_id, _e)

        msgs.append({
            "role": "user",
            "content": build_chapter_task_block(
                ch_title, chapter_words, overview=is_branch,
                writing_focus=_focus, chapter_path=_path,
            ),
        })

        # 首轮就给足预算：实测 303 章里 228 章首轮返回空流（思维链吃光 max_tokens）
        _max_tokens = max(2048, min(int(chapter_words * 3) + 512, 8192))
        collected: list[str] = []
        _meta: dict = {}
        async for chunk in gateway.stream_chat(
            messages=msgs, temperature=0.7, max_tokens=_max_tokens,
            no_thinking=True, meta=_meta,
        ):
            collected.append(chunk)
            if on_chunk is not None:
                try:
                    await on_chunk(chunk)
                except Exception:
                    pass
        full_content = _post_process_stream_content("".join(collected), ch_title, is_overview=is_branch, protect_names=protect_names)

        # 截断续写：finish_reason=="length" 表示不是写完而是被 max_tokens 截断的。
        # 分支概述（is_branch）本身就只有一小段，不适用续写。
        if not is_branch and full_content.strip():
            full_content = await _continue_if_truncated(
                gateway=gateway, msgs=msgs, content=full_content, ch_title=ch_title,
                target_words=chapter_words, max_tokens=_max_tokens,
                finish_reason=str(_meta.get("finish_reason") or ""),
                on_chunk=on_chunk,
                protect_names=protect_names,
            )

        if len(full_content.strip()) < 50:
            # 空流补救：换最简指令再要一次；再不行才退回显式占位。
            try:
                from services.generate.skills.content_gen_skill import ContentGenSkill as _CGS
                retry_msgs = [
                    {"role": "system", "content": (
                        f"请直接用简体中文写一段关于“{ch_title}”的本章概述，"
                        f"{max(MIN_CHAPTER_WORDS, chapter_words)} 字左右，以“本章”开头。"
                        "不要输出标题、不要输出 Markdown 标记、不要任何解释。"
                    )},
                    {"role": "user", "content": f"章节标题：{ch_title}。请开始撰写。"},
                ]
                retry_chunks: list[str] = []
                async for chunk in gateway.stream_chat(
                    messages=retry_msgs, temperature=0.7,
                    max_tokens=_max_tokens, no_thinking=True,
                ):
                    retry_chunks.append(chunk)
                    if on_chunk is not None:
                        # 重试也要推给前端，否则前端停在一段 <50 字的噪声上，
                        # 而库里存的是重试后的正文，用户再点保存就把噪声写回去了。
                        try:
                            await on_chunk(chunk)
                        except Exception:
                            pass
                retried = _post_process_stream_content("".join(retry_chunks), ch_title, is_overview=is_branch, protect_names=protect_names)
                if len(retried.strip()) >= 50:
                    full_content = retried
                elif _CGS._is_data_dependent_chapter(ch_title):
                    full_content = _CGS._generate_data_placeholder(ch_title)
                else:
                    full_content = _fallback_overview(ch_title)
                logger.info(
                    "[正文生成] 空流已补救 chapter=%s retry_len=%s final_len=%s",
                    ch_title, len(retried.strip()), len(full_content.strip()),
                )
            except Exception as _e:
                logger.warning(f"[正文生成] 空流重试失败 chapter={ch_title}: {_e}")
                full_content = _fallback_overview(ch_title)

        _blk = _failed_markers_in(full_content)
        if _blk:
            return ("failed", ch_id, ch_title, f"正文生成失败（{_blk[0]}）")

        # 生成后确定性修复：编造的报价/型号、抄错的设备参数、跨域商务条款、
        # 重复的备件大表。放在入库前做，所以单章重生成和批量生成都一样干净。
        if repair_ctx:
            try:
                from services.generate.skills.bid_consistency import repair_chapter
                _rep = repair_chapter(
                    ch_title, full_content, 0,
                    specs=repair_ctx.get("specs") or {},
                    allowed=repair_ctx.get("allowed") or set(),
                    exclusive=repair_ctx.get("exclusive") or {},
                    tender_text=repair_ctx.get("tender_text") or "",
                    ledger=repair_ctx.get("ledger") or None,
                )
                if _rep.changes:
                    logger.info(
                        "[一致性修复] chapter=%s 改动 %d 处: %s",
                        ch_title, len(_rep.changes), "；".join(_rep.changes[:6]),
                    )
                    # 只改入库内容，不往 SSE 里追加说明 —— 前端累积的正文必须
                    # 和库里存的一模一样，否则用户再点保存就把差异写回去了。
                    full_content = _rep.content
            except Exception as e:
                logger.warning("[一致性修复] 失败 chapter=%s: %s", ch_title, e)
        return ("ok", ch_id, ch_title, full_content)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"[正文生成] 章节异常 chapter={ch_title}: {e}")
        return ("error", ch_id, ch_title, str(e))


@router.get("/{project_id}/content/progress")
async def get_batch_progress(project_id: str):
    """查询项目当前的批量生成进度（关掉浏览器后重新打开也能看）。"""
    run = _BATCH_RUNS.get(project_id)
    if run is None:
        return {"project_id": project_id, "running": False, "total": 0,
                "completed": 0, "failed": 0, "failed_chapters": []}
    return run.payload()


@router.post("/{project_id}/content/stop")
async def stop_batch_generation(project_id: str):
    """显式停止该项目的批量生成任务。

    前端"停止批量生成"目前只 abort 了 fetch，服务端收不到；需要真正停下时
    调这个接口（或在阈值内关掉所有页面等 BMP_GEN_DETACH_GRACE 超时兜底）。
    """
    run = _BATCH_RUNS.get(project_id)
    if run is not None and run.task is not None and not run.task.done():
        run.task.cancel()
        logger.info("[批量生成] 收到显式停止请求 project_id=%s", project_id)
        return {"stopped": True, "project_id": project_id, "progress": run.payload()}
    return {"stopped": False, "project_id": project_id}


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
    tender_context = _build_tender_context(doc.parsed_content) if doc and doc.parsed_content else ""

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.project_id == project.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    mandatory_reqs = _extract_mandatory_requirements(analysis)

    gateway = get_llm_gateway()

    # 全局口径台账在流式生成器内部构建（见下），避免接口返回前先干等一次 LLM
    # 调用、前端却看不到任何进度。

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

    # ── 启动 / 接入生成任务 ────────────────────────────────────────
    # 真正的生成跑在独立的 asyncio.Task 里，SSE 只订阅事件。这样：
    #   ① 关掉浏览器不会中断生成（客户端断开只是少一个订阅者）；
    #   ② 每章一完成立刻落库，任何时刻中断都不会丢掉已完成的内容。
    _outline_id = outline.id if outline else None
    total = len(all_chapters)
    only_missing_flag = bool(only_missing)

    async def _batch_worker(run: "_BatchRun") -> None:
        _concurrency = max(1, int(os.getenv("BMP_GEN_CONCURRENCY", "2")))
        _interval = float(os.getenv("BMP_GEN_INTERVAL", "2.0"))
        _grace = _detach_grace_seconds()
        run.emit({"type": "start", "total": total, "only_missing": only_missing_flag})
        _write_gen_lock(project_id, {"total": total, "completed": 0, "failed": 0,
                                     "only_missing": only_missing_flag, "state": "ledger"})

        # ── 第一步：确定"全书唯一口径" ──────────────────────────────
        # 旧流程每章独立生成、各拍各的数字，实测同一份标书里质保期 3 种说法、
        # 投标有效期 3 种、到场时限 6 种、工作阻力从 280kN 到 42000kN。
        # 这里先跑一次台账提炼，之后每章的提示词都注入同一份表。
        ledger_text = ""
        _ledger: dict | None = None
        try:
            run.emit({"type": "stage", "stage": "ledger", "message": "正在统一全书商务口径..."})
            from services.database import async_session as _ledger_session
            _lf = _ledger_session()
            async with _lf() as _ldb:
                _ledger = await _get_or_build_ledger(_ldb, outline, project, gateway)
                await _ldb.commit()
            ledger_text = _format_ledger(_ledger)
            run.emit({
                "type": "ledger_ready",
                "items": len((_ledger or {}).get("items") or []),
                "params": len((_ledger or {}).get("key_params") or []),
            })
        except asyncio.CancelledError:
            raise
        except Exception as _le:
            logger.warning("[批量生成] 口径台账构建失败: %s", _le)
        if not ledger_text:
            logger.warning("[批量生成] 无全局口径台账，正文数字一致性没有前置约束")

        # ── 项目基本事实：全书恒定，注入每章 system（全局事实层）──
        # 旧版 project_facts 只喂给事后一致性检查与封面，**从不进正文**，
        # 于是正文里质保期出现 6 种取值、工作阻力 7 种。这里一次算好、每章共用。
        project_facts_text = ""
        try:
            project_facts_text = _format_project_facts(analysis, ledger_text)
            if project_facts_text:
                logger.info("[批量生成] 已注入项目基本事实 %d 字", len(project_facts_text))
            else:
                logger.warning("[批量生成] 解读结果里没有可用的项目基本事实，正文缺该层约束")
        except Exception as _fe:
            logger.warning("[批量生成] 项目基本事实构造失败: %s", _fe)

        # 企业/项目名称保护：禁止被清洗器的重复词规则折叠（名称与营业执照不一致=废标）
        protect_names = _protect_names_for(analysis, project)

        # ── 第二步：按标的物切分技术规格 ────────────────────────────
        # 招标文件里 3 台设备共有 6 组不同的 初撑力/工作阻力（整架表 + 立柱表），
        # 全量广播给每一章的结果是模型分不清谁是谁：实测端头支架章节写出
        # "初撑力12000kN、工作阻力16000kN"（招标文件里根本没有这两个数），
        # 超前支架章节抄了端尾的 7758/10000。这里先切好，再按章只注入对应段落。
        specs: dict = {}
        try:
            run.emit({"type": "stage", "stage": "specs", "message": "正在按标的物锁定技术参数..."})
            from services.database import async_session as _spec_session
            _sf = _spec_session()
            async with _sf() as _sdb:
                specs = await _get_or_build_specs(
                    _sdb, outline,
                    (doc.parsed_content if doc and doc.parsed_content else ""),
                    gateway,
                )
                await _sdb.commit()
            run.emit({"type": "specs_ready", "devices": list((specs or {}).keys())})
        except asyncio.CancelledError:
            raise
        except Exception as _se:
            logger.warning("[批量生成] 设备规格抽取失败: %s", _se)
        repair_ctx = _build_repair_ctx(
            (doc.parsed_content if doc and doc.parsed_content else ""), _ledger, specs
        )

        _sem = asyncio.Semaphore(_concurrency)
        all_contents: dict[str, str] = {}

        async def _gen_limited(ch_info):
            async with _sem:
                ch_id = ch_info["id"]
                ch_title = ch_info["title"]
                # 分支节点(有下级章节)只写本章概述,避免和下级章节内容/编号重复;
                # 叶子节点用预算分摊值,没设总字数时退回按标题推断。
                if ch_info.get("is_parent"):
                    chapter_words = OVERVIEW_WORDS
                elif per_leaf_words:
                    chapter_words = per_leaf_words
                else:
                    chapter_words = resolve_chapter_words(word_count, ch_title)
                result = await _generate_one_chapter(
                    project_id=project_id,
                    ch_id=ch_id,
                    ch_title=ch_title,
                    chapters_list=chapters_list,
                    tree=tree,
                    tender_context=tender_context,
                    mandatory_reqs=mandatory_reqs,
                    ledger_text=ledger_text,
                    mode=mode,
                    chapter_words=chapter_words,
                    is_branch=bool(ch_info.get("is_parent")),
                    gateway=gateway,
                    repair_ctx=repair_ctx,
                    # 把"前面已经写好的章节正文"回灌给本章 —— 修上下文不通畅。
                    # 按文档序分批后（_ordered_tasks），此处读到的必是文档序上
                    # 更靠前的章节，而不是"碰巧先跑完的那几章"。
                    all_contents=all_contents,
                    # 项目基本事实（名称/编号/采购人/工期/质保期…）
                    # 的全局事实层，全书恒定，进 system 不破坏前缀缓存。
                    project_facts_text=project_facts_text,
                    protect_names=protect_names,
                )
                await asyncio.sleep(_interval)
                return result

        _concurrency_note = _concurrency
        logger.info(
            "[批量生成] 启动 project_id=%s 章节=%s 并发=%s 间隔=%ss 游离宽限=%ss",
            project_id, total, _concurrency_note, _interval, _grace,
        )

        # ── 编排阶段（写作前全局统一决策）────────────────────────────
        # 在写正文之前，先用一次具备**全书视野**的调用决定"每节写什么、边界在哪"，
        # 产出 writing_focus 挂到大纲节点上。这是修"各章自说自话、上下文不通顺"
        # 的主要机制：把"让每章互相可见"换成了"上游一次决策 + 下游致盲"。
        # 已编排过就不重复调用（重启/续跑复用落库结果）；失败绝不阻断正文生成。
        if _content_plan_enabled() and not any(
            (n or {}).get("writing_focus") for n, _d in _iter_outline_nodes(chapters_list)
        ):
            try:
                from services.generate.skills.content_plan_skill import (
                    attach_plans as _attach_plans,
                    plan_writing_focus as _plan_writing_focus,
                )
                _t0 = time.time()
                # ① 编排进度上报：编排在 concurrency=1 时是串行的（几十个一级子树，
                #    实测 ~30 秒/个，可达 30 分钟），期间一章正文都没生成，
                #    前端进度条一直停在 0/N，用户会误判为"卡死"。
                #    这里把已完成的子树数实时发出去，让前端显示 n/m。
                _plans = await _plan_writing_focus(
                    chapters_list, key_info=ledger_text, gateway=gateway,
                    concurrency=_concurrency,
                    on_progress=lambda done, tot: run.emit({
                        "type": "plan_progress",
                        "done": done, "total": tot,
                        "chapter_title": f"正在编排写作计划 {done}/{tot}",
                    }),
                )
                _n = _attach_plans(chapters_list, _plans)
                logger.info(
                    "[正文编排] 完成 project_id=%s 挂载=%s 条 耗时=%.1fs",
                    project_id, _n, time.time() - _t0,
                )
                if _n:
                    run.emit({"type": "progress", "current": 0, "completed": 0,
                              "failed": 0, "total": total,
                              "chapter_title": f"已完成正文编排（{_n} 节）"})
                    # 落库：编排结果随大纲保存，重启/续跑复用，不再重复调用模型
                    if _outline_id:
                        try:
                            await _persist_outline_plans(_outline_id, chapters_list)
                        except Exception as _e:
                            logger.warning("[正文编排] 编排结果落库失败: %s", _e)
            except Exception as _e:
                logger.warning("[正文编排] 编排阶段失败（不影响正文生成）: %s", _e)

        gen_tasks: list = []

        async def _ordered_tasks():
            """按**文档序分批**产出已完成章节的结果。

            旧实现是一次性建好 213 个任务再 `as_completed`，实测完成顺序是
            `1,1.1,1.1.1,1.1.2,1.2,1.1.3,1.2.2,1.3…` —— 信号量虽然保证"开始
            顺序"是文档序，但窗口一放开，紧邻的前一个章节通常还在跑，于是
            "前文"其实只是**碰巧先跑完的那几章**，"承接/去重"没有可靠依据。

            改成按文档序分批后：上一批全部落定才开始下一批，因此本章在文档序
            上更靠前的章节（除同批至多 W-1 个）都已经写好，
            `build_prior_context_block` 拿到的"前面最近的章节"才真正是相邻章。

            W 取并发数，批内仍然 N 路并行，不牺牲吞吐。
            """
            _w = max(1, int(_concurrency))
            for _start in range(0, len(all_chapters), _w):
                _batch = all_chapters[_start:_start + _w]
                _tasks = [asyncio.create_task(_gen_limited(c)) for c in _batch]
                gen_tasks.extend(_tasks)
                for _t in asyncio.as_completed(_tasks):
                    yield await _t

        try:
            # 用 async for 消费：调用方的 break 会直接丢弃这个生成器，
            # 于是后续批次不会再被创建（停止/中止语义与原来一致）。
            async for status, ch_id, ch_title, payload in _ordered_tasks():
                # 兜底停止：一个订阅者都没有且持续超过宽限期，说明用户已经离开
                # （前端"停止批量生成"只 abort 了 fetch，服务端收不到停止信号）
                if run.detach_expired(_grace):
                    run.stopped_by_detach = True
                    logger.warning(
                        "[批量生成] 无订阅者超过 %ss，主动停止 project_id=%s（已完成 %s 章，均已落库）",
                        _grace, project_id, run.completed,
                    )
                    break

                seq = node_order.get(ch_id, 0)

                if status == "ok":
                    all_contents[ch_id] = payload
                    # ★★ 立刻落库：这是"关掉浏览器不丢内容"的关键。
                    # 旧实现把所有落库放在循环之后，一旦中断就全部丢失。
                    try:
                        await _persist_chapter_now(
                            _outline_id, project_id, ch_id, ch_title,
                            payload, mode, seq, "generated",
                        )
                    except Exception as _pe:
                        logger.warning("[批量生成] 落库失败 chapter=%s: %s", ch_title, _pe)
                        if _is_project_gone(_pe):
                            logger.error(
                                "[批量生成] 项目 %s 已被删除，中止剩余章节生成"
                                "（避免继续消耗模型配额）", project_id,
                            )
                            run.error = "项目已被删除，批量生成已中止"
                            run.emit({"type": "error", "message": run.error})
                            run.aborted = True
                            break
                    run.completed += 1
                    run.done_chapters.append(
                        {"id": ch_id, "title": ch_title, "word_count": len(payload)}
                    )
                    done = run.completed + run.failed
                    run.emit({"type": "progress", "current": done, "completed": run.completed,
                              "failed": run.failed, "total": total, "chapter_title": ch_title})
                    run.emit({"type": "chapter_done", "chapter_id": ch_id,
                              "chapter_title": ch_title, "word_count": len(payload),
                              "completed": run.completed, "total": total})
                else:
                    # 失败也要留痕：这样它既出现在前端"重新生成未加载内容（N 章）"
                    # 的计数里（内容<100字或含失败标记即算"需要重新生成"），
                    # 也会被导出门禁当成硬伤拦下，而不是悄悄变成"没有这一章"。
                    run.failed += 1
                    run.failed_chapters.append(
                        {"id": ch_id, "title": ch_title, "error": str(payload)[:300]}
                    )
                    logger.error("[批量生成] 章节%s(%s)失败: %s", ch_id, ch_title, payload)
                    try:
                        await _persist_chapter_now(
                            _outline_id, project_id, ch_id, ch_title,
                            _fallback_overview(ch_title), mode, seq, "failed",
                            preserve_existing=True,
                        )
                    except Exception as _pe:
                        logger.warning("[批量生成] 失败章节落库失败 chapter=%s: %s", ch_title, _pe)
                        if _is_project_gone(_pe):
                            logger.error(
                                "[批量生成] 项目 %s 已被删除，中止剩余章节生成", project_id,
                            )
                            run.error = "项目已被删除，批量生成已中止"
                            run.emit({"type": "error", "message": run.error})
                            run.aborted = True
                            break
                    done = run.completed + run.failed
                    run.emit({"type": "progress", "current": done, "completed": run.completed,
                              "failed": run.failed, "total": total, "chapter_title": ch_title})
                    run.emit({"type": "chapter_error", "chapter_id": ch_id,
                              "chapter_title": ch_title, "error": str(payload)[:200]})

                if done % 5 == 0:
                    _write_gen_lock(project_id, {
                        "total": total, "completed": run.completed, "failed": run.failed,
                        "only_missing": only_missing_flag, "state": "generating",
                    })
        except asyncio.CancelledError:
            logger.warning("[批量生成] 任务被取消 project_id=%s（已完成 %s 章）", project_id, run.completed)
            raise
        finally:
            for t in gen_tasks:
                if not t.done():
                    t.cancel()

        run.emit({"type": "post_check", "message": "正在进行生成后检查..."})

        # 确定性口径体检：不依赖 LLM，纯规则扫描跨章数字矛盾（质保期/投标有效期/
        # 到场时限/关键参数）。实测平台生成的标书里质保期有 3 种说法、投标有效期
        # 3 种、到场时限 6 种、工作阻力从 280kN 到 42000kN —— 这类"实质性内容前后
        # 不一致"在评标中通常按最不利于投标人的口径认定，甚至直接否决。
        # 放在这里是给用户一次"现在就改"的机会，导出时还会再拦一道。
        try:
            from services.generate.skills.norm_rules import (
                scan_commitment_conflicts, find_placeholders,
            )
            _full = "\n".join(all_contents.values())
            _conflicts = scan_commitment_conflicts(_full)
            if _conflicts:
                run.emit({"type": "commitment_conflicts", "data": _conflicts})
            _ph = find_placeholders(_full)
            if _ph:
                run.emit({"type": "placeholders", "data": _ph})
        except Exception as e:
            logger.warning(f"[批量生成] 口径体检失败: {e}")

        # 被兜底停掉时不再做 LLM 一致性检查：没人看结果，白烧一次调用
        if not run.stopped_by_detach:
            try:
                full_bid_text = "\n\n".join(all_contents.values())
                project_facts = _extract_project_facts(analysis)
                from services.check.skills.consistency_check_skill import ConsistencyCheckSkill
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
                consistency_result = await ConsistencyCheckSkill().safe_execute(consistency_ctx)
                if consistency_result.success:
                    run.emit({"type": "consistency_check", "data": consistency_result.data})
            except Exception as e:
                logger.warning(f"[批量生成] 一致性检查失败: {e}")

        try:
            # 把"评分项全表"传进去，未映射的评分项才不会被静默丢掉
            _score_items_for_cov: list[dict] = []
            try:
                if analysis is not None and getattr(analysis, "dimensions", None):
                    from services.generate.skills.structure_template_skill import (
                        extract_score_items,
                    )

                    _score_items_for_cov = extract_score_items(
                        (analysis.dimensions or {}).get("scoring", {}) or {}
                    )
            except Exception as e:
                logger.warning(f"[批量生成] 读取评分项全表失败: {e}")
            scoring_report = _check_scoring_coverage_inline(
                tree, all_contents, _score_items_for_cov
            )
            if scoring_report:
                run.emit({"type": "scoring_coverage", "data": scoring_report})
        except Exception as e:
            logger.warning(f"[批量生成] 评分覆盖检查失败: {e}")

        # ── 收尾：全书一致性修复 ────────────────────────────────────
        # 逐章修复看不到别的章节，跨章重复（同一张备件表被 12 章各粘一遍）
        # 只有整本一起看才能发现。这一步同时兜住"逐章修复被跳过"的章节。
        if not run.stopped_by_detach:
            try:
                run.emit({"type": "stage", "stage": "consistency",
                          "message": "正在做全书一致性校验..."})
                _rrep = await _repair_whole_book(
                    project_id,
                    (doc.parsed_content if doc and doc.parsed_content else ""),
                    _ledger, specs,
                )
                if _rrep is not None:
                    run.emit({
                        "type": "consistency_repair",
                        "total": _rrep.total_changes,
                        "by_kind": _rrep.by_kind,
                        "notes": _rrep.notes,
                        "summary": _rrep.summary(),
                    })
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[批量生成] 全书一致性修复失败: {e}")

        try:
            from services.database import async_session
            factory = async_session()
            async with factory() as pdb:
                proj_result = await pdb.execute(select(Project).where(Project.id == project_id))
                proj_record = proj_result.scalar_one_or_none()
                if proj_record:
                    proj_record.status = ProjectStatus.GENERATING
                await pdb.commit()
        except Exception as e:
            logger.warning(f"[批量生成] 项目状态更新失败: {e}")

        _clear_gen_lock(project_id)
        run.finished_at = time.time()
        run.emit({
            "type": "done", "total": total, "completed": run.completed, "failed": run.failed,
            "failed_chapters": run.failed_chapters[-80:],
            "stopped_by_detach": run.stopped_by_detach,
        })

    def _on_worker_done(t: asyncio.Task) -> None:
        """任务被取消/异常时也要收尾，否则前端永远等不到 done。"""
        if run.finished_at is not None:
            return
        run.finished_at = time.time()
        _clear_gen_lock(project_id)
        if t.cancelled():
            run.emit({"type": "done", "total": total, "completed": run.completed,
                      "failed": run.failed, "cancelled": True,
                      "failed_chapters": run.failed_chapters[-80:]})
            return
        exc = t.exception()
        if exc is not None:
            run.error = str(exc)
            logger.error("[批量生成] 任务异常 project_id=%s: %s", project_id, exc)
            run.emit({"type": "done", "total": total, "completed": run.completed,
                      "failed": run.failed, "error": str(exc),
                      "failed_chapters": run.failed_chapters[-80:]})

    # ── 跨进程去重 ────────────────────────────────────────────────
    # api 服务是 uvicorn --workers 2，内存里的运行表只对单个进程可见。
    # 用文件心跳标记保证同一项目只有一个进程真正在跑生成。
    async with _BATCH_RUNS_LOCK:
        run = _BATCH_RUNS.get(project_id)
        if run is not None and run.finished:
            run = None
        if run is None:
            other = _read_gen_lock(project_id)
            if other is not None:
                # 另一个 worker 正在跑：只做只读进度订阅，绝不再起一份
                await db.close()
                return StreamingResponse(
                    _mirror_other_run(project_id, other),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            run = _BatchRun(project_id, total, only_missing=only_missing_flag)
            _BATCH_RUNS[project_id] = run
            run.task = asyncio.create_task(_batch_worker(run))
            run.task.add_done_callback(_on_worker_done)
            # ② 独立心跳：防止慢章节（429 重试链可达数分钟）让运行标记被误判过期，
            #    从而导致同一项目被第二次点击新建出并行任务。
            run.heartbeat_task = asyncio.create_task(
                _gen_lock_heartbeat(project_id, run))
            logger.info("[批量生成] 新建任务 project_id=%s 章节=%s", project_id, total)
        else:
            logger.info("[批量生成] 接入已有任务 project_id=%s 进度=%s/%s",
                        project_id, run.completed + run.failed, run.total)

    async def subscriber():
        q = run.subscribe()
        try:
            # 先把历史事件补发一遍：刷新页面/重连后能立刻恢复进度显示
            for ev in list(run.history):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if run.finished:
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # 心跳，避免 nginx/浏览器把空闲连接判死
                    yield ": ping\n\n"
                    if run.finished:
                        return
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") == "done":
                    return
        finally:
            run.unsubscribe(q)

    # 生成器内部自带独立会话，这里提前归还 DI 会话的连接
    await db.close()
    return StreamingResponse(
        subscriber(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
                # 行内 `**加粗**` 必须解析成真正的粗体 run，否则星号原样进 Word。
                # 过去这里是 cell.text = cell_text（整格一个 run），从不解析标记，
                # 于是 `**合计**` 这类表内标记全部以字面星号交付。
                cell.text = ""
                _add_inline_runs(cell.paragraphs[0], cell_text, size=10.5)
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


# Markdown 无序项目符号：允许缩进（最多 8 空格）+ 符号 + 至少一个空格
_MD_BULLET_RE = re.compile(r"^([ \t]{0,8})[-*•]\s+(.+)$")


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
            # 第四级正文小标题渲染成"加粗段落"而不是 Heading 5。
            # 原因：实测一份标书里 Heading 5 有 323 段（1.1.1.1.1 这种五六级编号），
            # 目录层级被撑得又长又乱、Word 导航窗格完全不可用。正文小标题本身
            # 不需要进目录（TOC 只收 1-3 级），所以直接不做成标题样式。
            heading_text = line.lstrip("#").strip()
            para = doc.add_paragraph()
            para.paragraph_format.line_spacing = 1.5
            para.paragraph_format.space_before = Pt(6)
            run = para.add_run(heading_text)
            run.font.name = "宋体"
            run.font.size = Pt(12)
            run.bold = True
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

        # Markdown 项目符号行 -> 真正的 Word 项目符号段落。
        # 旧版没有这一支，"- 整架工作阻力：12500kN" 会落到下面的普通段落分支，
        # 把字面的 "- " 一起写进正文 —— 实测交付稿里有 **266 个段落以字面 "- " 
        # 开头**，在 Word 里就是一堆孤零零的连字符，属于最容易被评委看出的
        # "模板残留/排版不规范"。这里只处理无序符号（- * •）；
        # 有序编号（1. / 1、/（1））保持文本原样，因为中文标书里的编号写法
        # Word 自动编号复现不了，交给 List Number 反而会串号。
        m_list = _MD_BULLET_RE.match(line)
        if m_list:
            indent, body = m_list.group(1), m_list.group(2).strip()
            if body:
                style = "List Bullet"
                if len(indent.expandtabs(4)) >= 4:
                    style = "List Bullet 2"
                elif len(indent.expandtabs(4)) >= 2:
                    style = "List Bullet 2"
                try:
                    para = doc.add_paragraph(style=style)
                except KeyError:
                    # 模板里没有多级符号样式时退回一级，绝不因为样式缺失丢这一行
                    para = doc.add_paragraph(style="List Bullet")
                para.paragraph_format.line_spacing = 1.5
                para.paragraph_format.first_line_indent = Pt(0)
                _add_inline_runs(para, body)
                i += 1
                continue

        if line.strip():
            para = doc.add_paragraph()
            para.paragraph_format.line_spacing = 1.5
            para.paragraph_format.first_line_indent = Pt(24)
            _add_inline_runs(para, line.strip())

        i += 1


def _add_inline_runs(para, text: str, size: float = 12) -> None:
    """把正文里的 `**加粗**` 解析成真正的 Word 粗体 run，并去掉标记。

    实测缺陷：交付稿里有 **464 个 `**`、涉及 232 段**原样出现在 Word 正文中
    （如 `**投标截止日起算规则**`、`**合计**`）。原因是导出器只处理了**句首**
    的 `#### ` 分支，普通段落分支过去是 `para.add_run(line)` 整行一个 run，
    从不解析行内加粗标记 —— 于是标记变成了字面的星号，属于"排版不规范"里
    最扎眼的一类。

    用 re.split 的捕获组切分：偶数下标是普通文本，奇数下标是加粗内容。
    未配对的孤立 `**` 直接删掉，绝不让星号出现在成稿里。
    """
    if not text:
        return
    # 先清掉无法配对/嵌套异常的星号，再按成对标记切分
    text = re.sub(r"\*{3,}", "**", text)
    parts = re.split(r"\*\*(.+?)\*\*", text, flags=re.S)
    for idx, seg in enumerate(parts):
        if not seg:
            continue
        if idx % 2 == 0:
            seg = seg.replace("**", "")
            if not seg:
                continue
        run = para.add_run(seg)
        run.font.name = "宋体"
        run.font.size = Pt(size)
        if idx % 2 == 1:
            run.bold = True


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


# 正文小标题允许的最大编号层级。
# 实测导出的标书里出现了 1.1.1.1.1 / 1.1.1.1.1.1 这种五六级编号（Heading 5 共 323 段）：
# 一级原因是大纲本身退化到 4~5 级（见 outline_gen_skill 的深度上限），
# 二级原因是 _normalize_body_headings 会拿"已经很深的 node_id"再往后拼计数器。
# 这里把编号总深度封顶到 4 级，超出部分只保留标题文本、不再编号。
MAX_BODY_HEADING_DEPTH = 4


def _normalize_body_headings(content: str, node_id: str, descendant_ids: set[str] | None) -> str:
    """把章节正文里的 Markdown 小标题统一到全局编号。

    模型写正文时用的是"章内相对编号"(每一章的小标题都从 1.1 开始),导出成
    Heading2/3 之后就和真实章节号撞车 —— 实测第二章出现两个 2.1、两个 2.1.1。
    - 叶子章节:按本章节点号重排为 {节点号}.1 / {节点号}.1.1 …… 全局唯一。
      **但总深度封顶 MAX_BODY_HEADING_DEPTH 级**，避免 1.1.1.1.1.1。
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

    node_depth = str(node_id).count(".") + 1
    remain_levels = max(0, MAX_BODY_HEADING_DEPTH - node_depth)

    out: list[str] = []
    counters: dict[int, int] = {}
    for line in content.split("\n"):
        m = re.match(r"^(#{3,6})\s*(.*)$", line.strip())
        if not m:
            out.append(line)
            continue
        # ##### 及以上压到 ####，避免正文出现五级标题
        level = min(len(m.group(1)), 4)
        depth = max(1, level - 2)
        raw_title = m.group(2).strip()
        title = re.sub(r"^\d+(?:\.\d+)*[\s、.]*", "", raw_title).strip() or raw_title

        if depth > remain_levels:
            # 编号已经到顶（或本章节点本身就深），小标题不再编号
            out.append(f"{'#' * level} {title}")
            continue

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
    force: bool = Query(False),
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
    if not isinstance(force, bool):
        force = bool(getattr(force, "default", False))
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

    # ── 导出前门禁 ────────────────────────────────────────────────
    # 以前这里唯一的校验就是上面那句"有没有章节"，于是"【本章正文未能生成】"、
    # "ZL202310XXXXXX.X"、"某煤矿"、金额全是"—"的表格会直接导出成正式投标文件。
    # 现在做一次确定性体检，有硬伤就 409 拦下来，前端据此提示用户；确实要导
    # 也可以带 force=1 强制导出（保留逃生通道，避免用户被彻底卡死）。
    try:
        from services.generate.skills.norm_rules import scan_bid_document
        # 生成范围必须传进去：技术标独立成册按定义**不该**有投标函/报价表，
        # 而门禁的硬清单无条件要求它们 —— 不传范围就会把这类项目永久拦住
        # （见 norm_rules._MODE_EXCLUDED_CHAPTERS 的说明）。
        try:
            from services.generate.skills.chapter_attrs import (
                outline_mode_from_selection,
            )
            _outline_mode = outline_mode_from_selection(
                (project.config or {}).get("selected_structure_type")
            )
        except Exception as _ome:
            logger.warning("[导出前门禁] 生成范围判定失败，按完整投标文件体检: %s", _ome)
            _outline_mode = "response-file"
        _gate = scan_bid_document([
            {"id": str(c.id), "title": c.title, "content": c.content or ""}
            for c in chapters
        ], outline_mode=_outline_mode)
        logger.info("[导出前门禁] 生成范围=%s 阻断=%s 提示=%s",
                    _outline_mode, len(_gate.get("blockers") or []),
                    len(_gate.get("warnings") or []))
    except Exception as e:
        logger.warning("[导出前门禁] 体检失败，放行导出: %s", e)
        _gate = {"ok": True, "blockers": [], "warnings": []}

    if _gate.get("blockers") and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "标书存在会导致废标或明显不专业的问题，已阻止导出",
                "blockers": _gate["blockers"],
                "warnings": _gate.get("warnings", []),
                "hint": "修复后重新导出；确需强制导出请加 force=1（风险自负）",
            },
        )
    if _gate.get("warnings"):
        logger.info("[导出前门禁] 提示 %s 项: %s",
                    len(_gate["warnings"]), [w["kind"] for w in _gate["warnings"]])

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
            # 元语言清理也放在导出环节：库里已经生成的正文（实测一份标书 113 处
            # "本章旨在…""供评标委员会逐项核查打分"）不必重新生成就能去掉，
            # 否则这份改动只对新项目生效、老项目照旧。
            #
            # 但**导出这一遍必须和生成期同一套保护**，否则生成期保住的正文会在
            # 最后一步被删掉 —— 分支章（有下级章节）的"本章概述"职责就是交代
            # 本章范围与下级分工，天然带"本章系统…""本章主要包括…"，正是元语言
            # 清单里的短语，一剥就是整句消失：实测 266 字的概述剥完只剩 92 字，
            # 交付稿里那一章近乎空白。所以：
            #   ① 分支章概述不剥（它本来就该说这些）；
            #   ② 其余章节加"删减超 40% 即判误伤、保留原文"的安全网。
            _is_branch_ch = bool(descendants_of.get(node_id))
            if not _is_branch_ch:
                try:
                    from services.generate.skills.norm_rules import strip_meta_language
                    _before_len = len(body)
                    _stripped = strip_meta_language(body)
                    if _before_len >= 100 and len(_stripped) < _before_len * 0.60:
                        logger.error(
                            "[导出] 元语言清理删减 %s -> %s 字（%s），判定误伤，保留原文",
                            _before_len, len(_stripped), chapter.title,
                        )
                    else:
                        body = _stripped
                except Exception as _me:
                    logger.warning("[导出] 元语言清理失败(%s)：%s", chapter.title, _me)
            # 小标题统一到全局编号;父章节里重复列出的子章节标题直接删掉
            body = _normalize_body_headings(body, node_id, descendants_of.get(node_id))
            # 需要真实材料/图片的章节(营业执照、银行保函、保证金凭证、身份证明等):
            # 正文后附一个 1×1 表格,用灰色字写明此处需要插入什么图片。
            # 但**必须判重**：以前无条件追加，而正文里模型自己也会写
            # "【此处需插入图片：…】"（实测 11 处），于是同一章出现两条一模一样的
            # 提示；更要紧的是同一份材料被拆成 5-6 个章节时，这行提示会重复 6 次。
            if _IMAGE_CHAPTER_PAT.search(chapter.title or "") and "此处需插入图片" not in body:
                from services.generate.skills.content_gen_skill import ContentGenSkill as _CGS_EXPORT

                body = body.rstrip() + "\n\n" + _CGS_EXPORT._generate_data_placeholder(chapter.title)
            # 导出时再补一遍三项确定性清洗：清洗本来发生在**生成时**，所以对
            # "已经生成好、正文里已带瑕疵"的历史稿子（例如用户手里的《测试.docx》，
            # 含 6 处冗余四级编号标题、多段目录索引式导语、尺寸片段重复）不生效。
            # 放这里是为了让存量稿件**重新导出即可修正**，不必整本重生成。
            try:
                from services.generate.skills.content_cleaner import (
                    _dedup_dimension_fragments as _ddf,
                    _drop_redundant_level4_headings as _dl4,
                    _strip_index_boilerplate as _sib,
                )
                body = _dl4(body)
                body = _sib(body)
                body = _ddf(body)
            except Exception as _ce:
                logger.warning("[导出] 确定性清洗失败(%s)：%s", chapter.title, _ce)
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
