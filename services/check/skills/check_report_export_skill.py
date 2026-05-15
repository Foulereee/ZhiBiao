from __future__ import annotations

import io
import json
import logging
from datetime import datetime
from typing import Any

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


class CheckReportExportSkill(Skill):
    name = "check_report_export"
    description = "检查报告导出(Markdown/PDF/HTML)"
    category = "check"
    version = "1.0.0"
    triggers = ["导出报告", "报告导出", "检查报告"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        report_data = ctx.parameters.get("report_data", {})
        format_type = ctx.parameters.get("format", "markdown")
        project_name = ctx.parameters.get("project_name", "未命名项目")

        if not report_data:
            return SkillResult(success=False, error="无报告数据")

        if format_type == "markdown":
            content = self._to_markdown(report_data, project_name)
        elif format_type == "html":
            content = self._to_html(report_data, project_name)
        elif format_type == "json":
            content = json.dumps(report_data, ensure_ascii=False, indent=2)
        else:
            content = self._to_markdown(report_data, project_name)

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
        lines.append(f"# 投标文件检查报告")
        lines.append(f"")
        lines.append(f"**项目名称**: {project_name}")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"")

        checks = data.get("checks", [])
        if isinstance(checks, list):
            summary = data.get("summary", {})
            risk_level = data.get("risk_level", "unknown")

            risk_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(risk_level, "⚪")
            lines.append(f"## 检查概要")
            lines.append(f"")
            lines.append(f"- 风险等级: {risk_emoji} {risk_level}")
            if summary:
                lines.append(f"- 总检查项: {summary.get('total', len(checks))}")
                lines.append(f"- 通过: {summary.get('passed', 0)}")
                lines.append(f"- 不通过: {summary.get('failed', 0)}")
                lines.append(f"- 警告: {summary.get('warning', 0)}")
            lines.append(f"")

            lines.append(f"## 详细检查结果")
            lines.append(f"")
            lines.append(f"| 检查项 | 要求 | 实际 | 状态 | 说明 |")
            lines.append(f"|--------|------|------|------|------|")
            for check in checks:
                if isinstance(check, dict):
                    name = check.get("check_name", check.get("check_type", ""))
                    required = str(check.get("required", ""))[:30]
                    actual = str(check.get("actual", ""))[:30]
                    status = check.get("status", "unknown")
                    detail = str(check.get("detail", check.get("suggestion", "")))[:40]
                    status_icon = {"pass": "✅", "fail": "❌", "warning": "⚠️"}.get(status, status)
                    lines.append(f"| {name} | {required} | {actual} | {status_icon} {status} | {detail} |")
            lines.append(f"")

            failed = [c for c in checks if isinstance(c, dict) and c.get("status") == "fail"]
            if failed:
                lines.append(f"## ❌ 不通过项详情")
                lines.append(f"")
                for i, check in enumerate(failed, 1):
                    if isinstance(check, dict):
                        lines.append(f"### {i}. {check.get('check_name', check.get('check_type', ''))}")
                        lines.append(f"")
                        lines.append(f"- **招标要求**: {check.get('required', '')}")
                        lines.append(f"- **投标文件**: {check.get('actual', '')}")
                        lines.append(f"- **详细说明**: {check.get('detail', '')}")
                        suggestion = check.get("suggestion", "")
                        if suggestion:
                            lines.append(f"- **修改建议**: {suggestion}")
                        lines.append(f"")

        elif isinstance(data, dict):
            for key, value in data.items():
                if key in ("checks", "summary", "risk_level", "has_critical_issues"):
                    continue
                lines.append(f"## {key}")
                lines.append(f"")
                if isinstance(value, (list, dict)):
                    lines.append(f"```json")
                    lines.append(json.dumps(value, ensure_ascii=False, indent=2)[:2000])
                    lines.append(f"```")
                else:
                    lines.append(f"{value}")
                lines.append(f"")

        lines.append(f"---")
        lines.append(f"*报告由 BidMaster Pro 自动生成*")

        return "\n".join(lines)

    def _to_html(self, data: dict, project_name: str) -> str:
        md_content = self._to_markdown(data, project_name)

        html_parts = [
            "<!DOCTYPE html>",
            "<html><head><meta charset='utf-8'>",
            f"<title>检查报告 - {project_name}</title>",
            "<style>",
            "body { font-family: 'Microsoft YaHei', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }",
            "h1 { color: #1a56db; border-bottom: 2px solid #1a56db; padding-bottom: 8px; }",
            "h2 { color: #374151; margin-top: 24px; }",
            "table { border-collapse: collapse; width: 100%; margin: 12px 0; }",
            "th, td { border: 1px solid #d1d5db; padding: 8px 12px; text-align: left; }",
            "th { background: #f3f4f6; font-weight: 600; }",
            ".risk-high { color: #dc2626; font-weight: 700; }",
            ".risk-medium { color: #d97706; font-weight: 700; }",
            ".risk-low { color: #059669; font-weight: 700; }",
            ".pass { color: #059669; } .fail { color: #dc2626; } .warning { color: #d97706; }",
            "hr { border: none; border-top: 1px solid #e5e7eb; margin: 24px 0; }",
            "</style></head><body>",
        ]

        for line in md_content.split("\n"):
            if line.startswith("# "):
                html_parts.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):
                html_parts.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "):
                html_parts.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("- "):
                html_parts.append(f"<li>{line[2:]}</li>")
            elif line.startswith("| ") and "|" in line[1:]:
                cells = [c.strip() for c in line.split("|")[1:-1]]
                row = "".join(f"<td>{c}</td>" for c in cells)
                html_parts.append(f"<tr>{row}</tr>")
            elif line.startswith("---"):
                html_parts.append("<hr>")
            elif line.strip():
                html_parts.append(f"<p>{line}</p>")

        html_parts.append("</body></html>")
        return "\n".join(html_parts)
