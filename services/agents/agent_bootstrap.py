"""Agent 系统引导初始化。

注册所有 Agent 类、工具权限、Skill→ToolDef 包装、DB查询工具、Agent通信工具。
"""

from core.agent_framework.db_query_tools import DB_QUERY_TOOLS, DbQueryToolFactory
from core.agent_framework.registry import AgentRegistry
from core.agent_framework.tool import ToolRegistry
from core.agent_framework.types import ToolDef

from services.agents.skill_tool_adapter import wrap_skill_for_agent


# ─────────────────────────────────────────────
# 工具权限分配
# ─────────────────────────────────────────────

def register_tool_permissions(registry: ToolRegistry):
    """为每个 Agent 授予工具权限"""
    registry.grant_tools("tender_interpret_agent", [
        "dimension_extract", "scoring_matrix_build", "risk_identify",
        "search_knowledge_base", "query_analysis_db",
    ])
    registry.grant_tools("outline_agent", [
        "outline_generate", "score_alignment", "structure_template",
        "query_analysis_db", "ask_interpret_agent",
    ])
    registry.grant_tools("content_agent", [
        "chapter_generate", "content_expand", "image_generate",
        "query_analysis_db", "query_outline_db", "ask_outline_agent",
    ])
    registry.grant_tools("compliance_check_agent", [
        "compliance_check", "mandatory_check", "consistency_check",
        "query_analysis_db", "query_outline_db", "query_chapter_db",
        "query_check_report_db", "ask_interpret_agent",
    ])
    registry.grant_tools("format_agent", [
        "docx_format", "pdf_export", "revision_diff",
    ])
    registry.grant_tools("export_agent", [
        "pdf_export", "docx_export", "package_bundle",
    ])


# ─────────────────────────────────────────────
# DB 查询工具注册
# ─────────────────────────────────────────────

def register_db_query_tools(registry: ToolRegistry):
    """注册 DB 查询工具（Analysis/Outline/Chapter/CheckReport）"""
    for defn in DB_QUERY_TOOLS:
        registry.register_global(DbQueryToolFactory.create(defn))


# ─────────────────────────────────────────────
# Skill → ToolDef 包装注册
# ─────────────────────────────────────────────

def register_all_skill_tools(registry: ToolRegistry):
    """将现有 Skill 全部包装为 Agent 可调用的 ToolDef。

    映射关系：
    tender_interpret_agent: dimension_extract / scoring_matrix_build / risk_identify
    outline_agent:         outline_generate / score_alignment / structure_template
    content_agent:         chapter_generate / content_expand / image_generate
    compliance_check:      compliance_check / mandatory_check / consistency_check
    format_agent:          docx_format / revision_diff
    export_agent:          pdf_export / docx_export / package_bundle
    """

    # ── 解读类 Skill ──
    from services.interpret.skills.tender_interpret_skill import TenderInterpretSkill
    from services.interpret.skills.scoring_matrix_skill import ScoringMatrixSkill
    from services.interpret.skills.risk_alert_skill import RiskAlertSkill

    registry.register_global(wrap_skill_for_agent(
        TenderInterpretSkill, "dimension_extract",
        description="从招标文件中提取15个关键维度的信息（项目信息/资格要求/技术需求/评分标准等）",
        param_schema={
            "type": "object",
            "properties": {
                "dimensions": {
                    "type": "array", "items": {"type": "string"},
                    "description": "需要提取的维度ID列表，空表示全部。可选: project_info, buyer_info, qualification, technical, scoring, schedule, risk, eligibility, financial, contract, legal, documentation, evaluation, compliance, special"
                }
            },
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        ScoringMatrixSkill, "scoring_matrix_build",
        description="根据招标文件的评分标准构建评分矩阵，包括评分项、分值、评分标准",
        param_schema={
            "type": "object",
            "properties": {
                "scoring_data": {
                    "type": "string",
                    "description": "评分相关文本内容，空则从DB获取"
                }
            },
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        RiskAlertSkill, "risk_identify",
        description="识别招标文件中的潜在风险点、废标条款和注意事项",
        param_schema={
            "type": "object",
            "properties": {},
        },
    ))

    # ── 生成类 Skill ──
    from services.generate.skills.outline_gen_skill import OutlineGenSkill
    from services.generate.skills.structure_template_skill import StructureTemplateSkill, ScoreCoverageSkill
    from services.generate.skills.content_gen_skill import ContentGenSkill
    from services.generate.skills.content_expand_skill import ContentExpandSkill
    from services.generate.skills.ai_image_skill import AiImageSkill
    from services.generate.skills.knowledge_assist_skill import KnowledgeAssistSkill

    registry.register_global(wrap_skill_for_agent(
        OutlineGenSkill, "outline_generate",
        description="基于招标解读结果和评分矩阵生成投标文件大纲，自动对齐评分项",
        param_schema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string", "enum": ["aligned", "free"],
                    "description": "生成模式：aligned=对齐评分项生成，free=自由生成"
                },
                "count": {
                    "type": "integer",
                    "description": "期望的章节数量"
                }
            },
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        ScoreCoverageSkill, "score_alignment",
        description="检查大纲章节与评分项的覆盖对齐情况，识别未覆盖的评分项",
        param_schema={
            "type": "object",
            "properties": {},
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        StructureTemplateSkill, "structure_template",
        description="获取标准投标文件结构模板（按项目类型：工程/货物/服务）",
        param_schema={
            "type": "object",
            "properties": {
                "project_type": {
                    "type": "string",
                    "description": "项目类型: engineering/goods/service"
                }
            },
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        ContentGenSkill, "chapter_generate",
        description="根据大纲章节标题和解读结果生成投标内容，支持自动配图",
        param_schema={
            "type": "object",
            "properties": {
                "chapter_title": {
                    "type": "string",
                    "description": "章节标题"
                },
                "chapter_outline": {
                    "type": "string",
                    "description": "章节大纲/子节结构"
                },
                "tender_context": {
                    "type": "string",
                    "description": "招标文件相关上下文"
                },
                "word_count": {
                    "type": "integer",
                    "description": "目标字数，默认3000"
                },
                "mode": {
                    "type": "string", "enum": ["A", "B", "C", "D"],
                    "description": "生成模式: A=完整生成+模板化规范, B=快速生成, C=极简, D=大纲模式"
                },
                "enable_illustration": {
                    "type": "boolean",
                    "description": "是否自动生成配图"
                }
            },
            "required": ["chapter_title"],
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        ContentExpandSkill, "content_expand",
        description="扩写/细化已有的投标内容",
        param_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "需要扩写的内容"},
                "target_words": {"type": "integer", "description": "目标字数"},
            },
            "required": ["content"],
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        AiImageSkill, "image_generate",
        description="根据章节内容自动生成配图（流程图/架构图/示意图）",
        param_schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "图片描述/章节内容摘要"},
                "image_size": {
                    "type": "string",
                    "description": "图片尺寸: landscape_16_9/portrait_4_3/square等"
                },
            },
            "required": ["prompt"],
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        KnowledgeAssistSkill, "search_knowledge_base",
        description="搜索知识库获取补充信息（法规/模板/历史案例）",
        param_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询"},
            },
            "required": ["query"],
        },
    ))

    # ── 检查类 Skill ──
    from services.check.skills.compliance_check_skill import ComplianceCheckSkill
    from services.check.skills.mandatory_req_check_skill import MandatoryReqCheckSkill
    from services.check.skills.consistency_check_skill import ConsistencyCheckSkill

    registry.register_global(wrap_skill_for_agent(
        ComplianceCheckSkill, "compliance_check",
        description="全面检查投标文件的合规性，逐条对照招标文件硬性要求",
        param_schema={
            "type": "object",
            "properties": {
                "tender_text": {"type": "string", "description": "招标文件相关文本"},
                "bid_text": {"type": "string", "description": "投标文件内容"},
            },
            "required": ["tender_text", "bid_text"],
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        MandatoryReqCheckSkill, "mandatory_check",
        description="检查强制性要求（资质/保证金/签字盖章等）是否满足",
        param_schema={
            "type": "object",
            "properties": {
                "tender_text": {"type": "string", "description": "招标文件强制性要求原文"},
                "bid_text": {"type": "string", "description": "投标文件响应内容"},
            },
            "required": ["tender_text", "bid_text"],
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        ConsistencyCheckSkill, "consistency_check",
        description="检查投标文件前后一致性和数据一致性",
        param_schema={
            "type": "object",
            "properties": {
                "bid_text": {"type": "string", "description": "投标文件全文"},
            },
            "required": ["bid_text"],
        },
    ))

    # ── 格式化/导出 Skill ──
    from services.format.skills.docx_format_skill import DocxFormatSkill
    from services.format.skills.pdf_export_skill import PdfExportSkill
    from services.format.skills.revision_skill import RevisionSkill

    registry.register_global(wrap_skill_for_agent(
        DocxFormatSkill, "docx_format",
        description="将投标内容排版为 DOCX 格式文档",
        param_schema={
            "type": "object",
            "properties": {
                "template": {"type": "string", "description": "模板名称"},
            },
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        PdfExportSkill, "pdf_export",
        description="将投标文件导出为 PDF 格式",
        param_schema={
            "type": "object",
            "properties": {},
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        PdfExportSkill, "docx_export",
        description="将投标文件导出为 DOCX 格式",
        param_schema={
            "type": "object",
            "properties": {},
        },
    ))

    registry.register_global(wrap_skill_for_agent(
        RevisionSkill, "revision_diff",
        description="对比两个版本的投标文件差异",
        param_schema={
            "type": "object",
            "properties": {
                "old_version": {"type": "string", "description": "旧版本内容"},
                "new_version": {"type": "string", "description": "新版本内容"},
            },
            "required": ["old_version", "new_version"],
        },
    ))

    # ── 打包导出 Skill ──
    from services.check.skills.check_report_export_skill import CheckReportExportSkill

    registry.register_global(wrap_skill_for_agent(
        CheckReportExportSkill, "package_bundle",
        description="打包所有投标文件（正文+附件+签章）",
        param_schema={
            "type": "object",
            "properties": {},
        },
    ))


# ─────────────────────────────────────────────
# Agent 间通信工具
# ─────────────────────────────────────────────

def register_agent_comm_tools(registry: ToolRegistry):
    """注册 Agent 间通信工具（ask_xxx_agent）。

    这些工具允许 Agent 通过 MessageBus 向其他 Agent 提问。
    遵循 DB 优先原则：先查 DB，DB 无法满足时才使用通信工具。
    """

    def _make_ask_handler(target_agent: str):
        """为 ask_xxx_agent 创建 handler（闭包捕获 target_agent）"""
        async def handler(question: str, **kw):
            if not hasattr(handler, '_agent_ctx') or not handler._agent_ctx:
                return {"error": "Agent上下文未初始化"}
            ctx = handler._agent_ctx
            if not ctx.message_bus:
                return {"error": "MessageBus 不可用"}
            # 防御：sender 必须已设置（在 ctx_provider 中注入）
            sender = getattr(handler, '_sender_agent', None)
            if not sender:
                return {"error": "发送方Agent未设置"}
            result = await ctx.message_bus.request_response(
                sender=sender,
                receiver=target_agent,
                content=question,
                timeout=30.0,
            )
            if isinstance(result, dict) and "error" in result:
                return result
            return {"answer": result}

        def ctx_provider(ctx):
            handler._agent_ctx = ctx
            handler._sender_agent = ctx.agent_name  # 设置发送方Agent名

        return handler, ctx_provider

    # ask_interpret_agent
    handler_interpret, provider_interpret = _make_ask_handler("tender_interpret_agent")
    handler_interpret._sender_agent = None  # 由 Agent.__init__ 或 run 时设置
    registry.register_global(ToolDef(
        name="ask_interpret_agent",
        description="向招标解读Agent提问，获取招标文件的解读信息。仅当DB查询无法满足时使用（延迟约5-15秒）",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "需要向解读Agent提问的内容"},
            },
            "required": ["question"],
        },
        handler=handler_interpret,
        ctx_provider=provider_interpret,
    ))

    # ask_outline_agent
    handler_outline, provider_outline = _make_ask_handler("outline_agent")
    handler_outline._sender_agent = None
    registry.register_global(ToolDef(
        name="ask_outline_agent",
        description="向大纲Agent确认结构相关的问题。仅当DB查询无法满足时使用（延迟约5-15秒）",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "需要向大纲Agent提问的内容"},
            },
            "required": ["question"],
        },
        handler=handler_outline,
        ctx_provider=provider_outline,
    ))


# ─────────────────────────────────────────────
# 全部工具注册入口
# ─────────────────────────────────────────────

def register_all_tools(registry: ToolRegistry):
    """一次性注册所有工具（供 agent_runtime 调用）"""
    register_all_skill_tools(registry)
    register_db_query_tools(registry)
    register_agent_comm_tools(registry)
    register_tool_permissions(registry)


# ─────────────────────────────────────────────
# Agent 注册表创建
# ─────────────────────────────────────────────

def create_agent_registry() -> AgentRegistry:
    """创建并注册所有6个 Agent 类"""
    registry = AgentRegistry()

    from services.agents.compliance_check_agent import ComplianceCheckAgent
    from services.agents.content_agent import ContentAgent
    from services.agents.export_agent import ExportAgent
    from services.agents.format_agent import FormatAgent
    from services.agents.outline_agent import OutlineAgent
    from services.agents.tender_interpret_agent import TenderInterpretAgent

    registry.register(TenderInterpretAgent)
    registry.register(OutlineAgent)
    registry.register(ContentAgent)
    registry.register(ComplianceCheckAgent)
    registry.register(FormatAgent)
    registry.register(ExportAgent)

    return registry