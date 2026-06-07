from dataclasses import dataclass
from typing import Any

from core.agent_framework.types import AgentContext, ToolDef

_MODEL_MAP: dict[str, Any] = {}


def _get_model(name: str):
    if name not in _MODEL_MAP:
        from services.models import Analysis, Chapter, CheckReport, Outline
        _MODEL_MAP.update({
            "Analysis": Analysis,
            "Outline": Outline,
            "Chapter": Chapter,
            "CheckReport": CheckReport,
        })
    return _MODEL_MAP.get(name)


@dataclass
class DbQueryDef:
    tool_name: str
    description: str
    model_name: str
    result_summarizer: callable
    project_id_field: str = "project_id"


class DbQueryToolFactory:

    @staticmethod
    def create(defn: DbQueryDef) -> ToolDef:
        param_schema = {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array", "items": {"type": "string"},
                    "description": "需要的字段列表，空表示全部",
                }
            },
        }

        async def handler(fields: list[str] | None = None, **kw):
            ctx: AgentContext = handler._agent_ctx
            if not ctx or not ctx.db:
                return {"error": "数据库连接不可用"}
            model = _get_model(defn.model_name)
            if not model:
                return {"error": f"模型 {defn.model_name} 未注册"}

            from sqlalchemy import select
            stmt = select(model).where(
                getattr(model, defn.project_id_field) == ctx.project_id
            )
            result = await ctx.db.execute(stmt)
            record = result.scalar_one_or_none()
            if not record:
                return {"error": f"{defn.description}不存在"}
            return defn.result_summarizer(record, fields)

        def ctx_provider(ctx: AgentContext):
            handler._agent_ctx = ctx

        return ToolDef(
            name=defn.tool_name,
            description=defn.description,
            parameters=param_schema,
            handler=handler,
            ctx_provider=ctx_provider,
        )


DB_QUERY_TOOLS = [
    DbQueryDef(
        tool_name="query_analysis_db",
        description="查询招标解读结果（维度/评分矩阵/废标条款）",
        model_name="Analysis",
        result_summarizer=lambda r, f: {
            "dimensions": list(r.dimensions.keys()) if r.dimensions else [],
            "scoring_matrix": r.scoring_matrix if hasattr(r, 'scoring_matrix') else {},
            "risk_flags": r.risk_flags if hasattr(r, 'risk_flags') else {},
        },
    ),
    DbQueryDef(
        tool_name="query_outline_db",
        description="查询投标大纲",
        model_name="Outline",
        result_summarizer=lambda r, f: {
            "mode": r.mode,
            "chapter_count": len(r.tree) if isinstance(r.tree, list) else 0,
            "chapters": [c.get("title") for c in (r.tree or [])[:20]],
        },
    ),
    DbQueryDef(
        tool_name="query_chapter_db",
        description="查询已生成的章节内容",
        model_name="Chapter",
        result_summarizer=lambda r, f: {
            "title": r.title, "status": r.status, "word_count": r.word_count,
            "content_preview": (r.content or "")[:200],
        },
    ),
    DbQueryDef(
        tool_name="query_check_report_db",
        description="查询检查报告结果",
        model_name="CheckReport",
        result_summarizer=lambda r, f: {
            "type": r.type, "risk_level": r.risk_level,
            "summary": r.summary,
            "has_critical": r.results.get("has_critical_issues", False) if r.results else False,
        },
    ),
]
