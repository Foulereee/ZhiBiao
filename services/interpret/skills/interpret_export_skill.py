from __future__ import annotations

import json
from datetime import datetime

from core.skill_engine.base import Skill, SkillContext, SkillResult


class InterpretExportSkill(Skill):
    name = "interpret_export"
    description = "解读报告导出(I-08): 生成结构化解读报告(Markdown/HTML/PDF)"
    category = "interpret"
    version = "1.0.0"
    triggers = ["解读导出", "解读报告", "导出解读"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        interpret_data = ctx.parameters.get("interpret_data", {})
        format_type = ctx.parameters.get("format", "markdown")
        project_name = ctx.parameters.get("project_name", "未命名项目")

        if not interpret_data:
            return SkillResult(success=False, error="解读数据为空")

        if format_type == "markdown":
            content = self._to_markdown(interpret_data, project_name)
        elif format_type == "html":
            content = self._to_html(interpret_data, project_name)
        elif format_type == "json":
            content = json.dumps(interpret_data, ensure_ascii=False, indent=2)
        else:
            content = self._to_markdown(interpret_data, project_name)

        return SkillResult(
            success=True,
            data={
                "content": content,
                "format": format_type,
                "size": len(content.encode("utf-8")),
                "generated_at": datetime.now().isoformat(),
            },
        )

    def _to_markdown(self, data: dict, project_name: str) -> str:
        lines = []
        lines.append("# 招标文件解读报告")
        lines.append("")
        lines.append(f"**项目名称**: {project_name}")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        dimensions = data.get("dimensions", data)
        if isinstance(dimensions, dict):
            for dim_id, dim_data in dimensions.items():
                dim_name = self._dimension_display_name(dim_id)
                lines.append(f"## {dim_name}")
                lines.append("")

                if isinstance(dim_data, dict):
                    if dim_data.get("error"):
                        lines.append(f"> 解读失败: {dim_data['error']}")
                        lines.append("")
                        continue
                    for key, value in dim_data.items():
                        if value is None:
                            continue
                        display_key = self._key_display_name(key)
                        if isinstance(value, list):
                            lines.append(f"### {display_key}")
                            lines.append("")
                            for i, item in enumerate(value, 1):
                                if isinstance(item, dict):
                                    lines.append(f"**{i}.** " + " | ".join(
                                        f"{self._key_display_name(k)}: {v}" for k, v in item.items() if v is not None
                                    ))
                                else:
                                    lines.append(f"- {item}")
                            lines.append("")
                        elif isinstance(value, dict):
                            lines.append(f"### {display_key}")
                            lines.append("")
                            for k, v in value.items():
                                if v is not None:
                                    lines.append(f"- **{self._key_display_name(k)}**: {v}")
                            lines.append("")
                        else:
                            lines.append(f"- **{display_key}**: {value}")
                    lines.append("")
                elif isinstance(dim_data, list):
                    for item in dim_data:
                        if isinstance(item, dict):
                            lines.append("- " + " | ".join(
                                f"{k}: {v}" for k, v in item.items() if v is not None
                            ))
                        else:
                            lines.append(f"- {item}")
                    lines.append("")

        risk_alerts = data.get("risks", data.get("risk_alerts", []))
        if risk_alerts:
            lines.append("## 风险预警")
            lines.append("")
            for risk in risk_alerts:
                if isinstance(risk, dict):
                    severity = risk.get("severity", "medium")
                    severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
                    lines.append(f"### {severity_icon} {risk.get('title', '风险项')}")
                    lines.append("")
                    lines.append(f"- **类别**: {risk.get('category', '')}")
                    lines.append(f"- **原文**: {risk.get('content', '')}")
                    lines.append(f"- **分析**: {risk.get('analysis', '')}")
                    suggestion = risk.get("suggestion", "")
                    if suggestion:
                        lines.append(f"- **建议**: {suggestion}")
                    lines.append("")

        lines.append("---")
        lines.append("*报告由 BidMaster Pro 自动生成*")

        return "\n".join(lines)

    def _to_html(self, data: dict, project_name: str) -> str:
        md_content = self._to_markdown(data, project_name)

        html_parts = [
            "<!DOCTYPE html>",
            "<html><head><meta charset='utf-8'>",
            f"<title>解读报告 - {project_name}</title>",
            "<style>",
            "body { font-family: 'Microsoft YaHei', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }",
            "h1 { color: #1a56db; border-bottom: 2px solid #1a56db; padding-bottom: 8px; }",
            "h2 { color: #374151; margin-top: 24px; border-left: 4px solid #1a56db; padding-left: 12px; }",
            "h3 { color: #4b5563; }",
            "table { border-collapse: collapse; width: 100%; margin: 12px 0; }",
            "th, td { border: 1px solid #d1d5db; padding: 8px 12px; text-align: left; }",
            "th { background: #f3f4f6; font-weight: 600; }",
            "blockquote { border-left: 4px solid #ef4444; background: #fef2f2; padding: 8px 16px; margin: 8px 0; }",
            "hr { border: none; border-top: 1px solid #e5e7eb; margin: 24px 0; }",
            ".risk-critical { color: #dc2626; } .risk-high { color: #ea580c; }",
            ".risk-medium { color: #d97706; } .risk-low { color: #059669; }",
            "</style></head><body>",
        ]

        for line in md_content.split("\n"):
            if line.startswith("# "):
                html_parts.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):
                html_parts.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "):
                html_parts.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("> "):
                html_parts.append(f"<blockquote>{line[2:]}</blockquote>")
            elif line.startswith("- "):
                html_parts.append(f"<li>{line[2:]}</li>")
            elif line.startswith("---"):
                html_parts.append("<hr>")
            elif line.strip():
                html_parts.append(f"<p>{line}</p>")

        html_parts.append("</body></html>")
        return "\n".join(html_parts)

    def _dimension_display_name(self, dim_id: str) -> str:
        name_map = {
            "project_info": "项目信息",
            "buyer_info": "甲方信息",
            "qualification": "资格要求",
            "technical": "技术需求",
            "scoring": "评分细则",
            "disqualification": "废标红线",
            "deposit": "保证金",
            "opening": "开标要求",
            "evaluation": "评标办法",
            "commercial": "商务评分",
            "contract": "合同条款",
            "risk": "风险提示",
            "competition": "竞争态势",
            "timeline": "时间节点",
            "contacts": "关键联系人",
        }
        return name_map.get(dim_id, dim_id)

    def _key_display_name(self, key: str) -> str:
        if "_" in key:
            parts = key.split("_")
            return "".join(p.capitalize() for p in parts)
        return key
