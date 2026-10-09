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
        # 报告"生成时间"要用报告自己的创建时间，不能用"此刻"：
        # 后者每打开一次预览就变一次，同一份报告在列表、预览、导出 Word 里
        # 会出现三个不同的时间（用户反馈"列表时间不对、预览里是对的"根因之一）。
        report_time = str(ctx.parameters.get("report_time") or "")

        if not report_data:
            return SkillResult(success=False, error="无报告数据")

        if format_type == "markdown":
            content = self._to_markdown(report_data, project_name, report_time)
        elif format_type == "html":
            content = self._to_html(report_data, project_name, report_time)
        elif format_type == "json":
            content = json.dumps(report_data, ensure_ascii=False, indent=2)
        else:
            content = self._to_markdown(report_data, project_name, report_time)

        return SkillResult(
            success=True,
            data={
                "content": content,
                "format": format_type,
                "size": len(content.encode("utf-8")),
                "generated_at": datetime.now().astimezone().isoformat(),
            },
        )

    # 风险等级/状态的中文说法:客户看不懂 high/fail 这类内部值
    _RISK_CN = {"high": "高风险", "medium": "中风险", "low": "低风险", "unknown": "未评估"}
    _STATUS_CN = {"pass": "通过", "fail": "不通过", "warning": "需注意", "unknown": "未评估"}
    # 命中这些关键词的不通过项,极可能导致废标/资格不通过
    _FATAL_KEYS = ("废标", "资格", "否决", "无效投标", "实质性", "保证金", "密封", "签章")

    def _conclusion_lines(self, checks: list, summary: dict, risk_level: str) -> list:
        """把检查结果翻译成客户看得懂的「一句话结论 + 先改哪几件事」。"""
        # 汇总行只是"目录",不计入条数统计,否则"共检查 28 项"与"26 条要求"对不上
        counted = [c for c in checks if isinstance(c, dict) and not c.get("is_summary")] or list(checks)
        item_mode = bool((summary or {}).get("item_mode")) or any(
            isinstance(c, dict) and c.get("is_summary") for c in checks
        )
        unit = "条" if item_mode else "项"

        def _num(key: str, status: str) -> int:
            if summary and summary.get(key) is not None:
                return int(summary.get(key) or 0)
            return sum(1 for c in counted if isinstance(c, dict) and c.get("status") == status)

        total = (summary or {}).get("total") or len(counted)
        passed = _num("passed", "pass")
        failed = _num("failed", "fail")
        warning = _num("warning", "warning")
        unknown = _num("unknown", "unknown") or sum(
            1 for c in counted if isinstance(c, dict) and c.get("status") == "unknown"
        )

        fail_items = [c for c in counted if isinstance(c, dict) and c.get("status") == "fail"]
        fatal = [
            c
            for c in fail_items
            if any(
                k in f"{c.get('check_name', '')}{c.get('check_type', '')}{c.get('required', '')}"
                for k in self._FATAL_KEYS
            )
        ]
        unknown_items = [c for c in counted if isinstance(c, dict) and c.get("status") == "unknown"]

        out = ["## 一句话结论", ""]
        if item_mode:
            line = (
                f"本次共逐条核对 **{total}** 条明细：符合 {passed} 条，"
                f"**不符合 {failed} 条**，需注意 {warning} 条。"
            )
        else:
            line = f"本次共检查 **{total}** 项：通过 {passed} 项，**不通过 {failed} 项**，需注意 {warning} 项。"
        if unknown:
            line += f"另有 **{unknown} {unit}未取得有效结果**。"
        out.append(line)
        if fatal:
            out.append(
                f"⚠️ 其中 **{len(fatal)} 项可能直接导致废标或资格审查不通过**，必须在提交前优先修改，"
                "否则投标文件存在被否决的风险。"
            )
        elif failed:
            out.append("未发现直接导致废标的条款，但不通过项会影响评分或需要补正，建议提交前逐项修改。")
        elif unknown:
            # 空壳结果绝不能报"通过":之前客户拿到的正是这种"没检查却写已通过"的报告
            out.append(
                f"⚠️ 有 {unknown} {unit}检查未取得有效结果（未评估），**不能据此认为已通过**，"
                "请重新运行这些检查后再决定是否提交。"
            )
        else:
            out.append("未发现不通过项，可以按正常流程提交。")
        out.append("")

        if fail_items:
            # 优先挑"具体条款"级的不通过项(带招标要求原文),避免把汇总行的统计数字当成修改建议
            generic_req = ("", "—", "-", "见招标文件对应条款")
            picks = [
                c for c in fail_items if str(c.get("required", "") or "").strip() not in generic_req
            ] or fail_items
            out.append("### 建议优先修改的前 3 项")
            out.append("")
            for i, c in enumerate(picks[:3], 1):
                name = c.get("check_name") or c.get("check_type") or "未命名检查项"
                req = str(c.get("required", "") or "")[:150]
                act = str(c.get("actual", "") or "")[:150]
                fix = str(c.get("suggestion", "") or "").strip()
                # 汇总行的"未响应条数 13；条款总数 20"不是可执行建议,换成通用指引
                if not fix or any(k in fix for k in ("条数", "条款总数", "共检查")):
                    fix = ""
                fix = fix[:200] or "按招标文件要求补充或修正对应内容"
                out.append(f"**{i}. {name}**")
                out.append("")
                if req:
                    out.append(f"- 招标要求：{req}")
                if act:
                    out.append(f"- 我方现状：{act}")
                out.append(f"- 怎么改：{fix}")
                out.append("")
            if len(picks) > 3:
                out.append(f"（其余 {len(picks) - 3} 项见下方「❌ 不通过项详情」。）")
                out.append("")

        if unknown_items:
            out.append("### ⚠️ 未能判定的检查项（需重新运行）")
            out.append("")
            for c in unknown_items[:5]:
                name = c.get("check_name") or c.get("check_type") or "未命名检查项"
                out.append(f"- **{name}**：{str(c.get('detail') or '未取得有效结果')[:140]}")
            out.append("")

        return out

    def _to_markdown(self, data: dict, project_name: str, report_time: str = "") -> str:
        lines = []
        lines.append(f"# 投标文件检查报告")
        lines.append(f"")
        lines.append(f"**项目名称**: {project_name}")
        lines.append(f"**生成时间**: {report_time or datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"")

        checks = data.get("checks", [])
        if isinstance(checks, list):
            summary = data.get("summary", {}) or {}
            risk_level = data.get("risk_level", "unknown")
            risk_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(risk_level, "⚪")

            def _cell(value, limit: int = 120) -> str:
                """单元格里的 | 和换行会破坏表格结构,统一清洗后再按长度截断。"""
                text = str(value if value is not None else "").replace("|", "／")
                text = text.replace("\r", " ").replace("\n", " ").strip()
                return text[:limit]

            # 先给客户一句能看懂的结论 + 先改哪三件事,再给明细表
            lines.extend(self._conclusion_lines(checks, summary, risk_level))

            item_mode = bool((summary or {}).get("item_mode")) or any(
                isinstance(c, dict) and c.get("is_summary") for c in checks
            )
            counted = [c for c in checks if isinstance(c, dict) and not c.get("is_summary")] or list(checks)

            def _cnt(key: str, status: str) -> int:
                if summary and summary.get(key) is not None:
                    return int(summary.get(key) or 0)
                return sum(1 for c in counted if c.get("status") == status)

            lines.append(f"## 检查概要")
            lines.append(f"")
            lines.append(f"- 风险等级: {risk_emoji} {self._RISK_CN.get(risk_level, risk_level)}")
            if item_mode:
                lines.append(f"- 逐条核对明细: {len(counted)} 条")
            else:
                lines.append(f"- 总检查项: {len(counted)}")
            lines.append(f"- 通过: {_cnt('passed', 'pass')}")
            lines.append(f"- 不通过: {_cnt('failed', 'fail')}")
            lines.append(f"- 需注意: {_cnt('warning', 'warning')}")
            unassessed = _cnt("unknown", "unknown")
            if unassessed:
                lines.append(f"- 未评估（需重跑）: {unassessed}")
            lines.append(f"")

            lines.append(f"## 详细检查结果")
            lines.append(f"")
            lines.append(f"| 检查项 | 要求 | 实际 | 状态 | 说明 |")
            lines.append(f"|--------|------|------|------|------|")
            for check in checks:
                if isinstance(check, dict):
                    name = _cell(check.get("check_name", check.get("check_type", "")), 56)
                    required = _cell(check.get("required", ""), 180)
                    actual = _cell(check.get("actual", ""), 180)
                    status = check.get("status", "unknown")
                    detail = _cell(check.get("detail", check.get("suggestion", "")), 240)
                    status_icon = {"pass": "✅", "fail": "❌", "warning": "⚠️"}.get(status, "⚪")
                    lines.append(
                        f"| {name} | {required} | {actual} | {status_icon} {self._STATUS_CN.get(status, status)} | {detail} |"
                    )
            lines.append(f"")

            failed = [
                c for c in checks
                if isinstance(c, dict) and c.get("status") == "fail" and not c.get("is_summary")
            ]
            if failed:
                lines.append(f"## ❌ 不通过项详情")
                lines.append(f"")
                for i, check in enumerate(failed[:40], 1):
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
                if len(failed) > 40:
                    lines.append(f"（其余 {len(failed) - 40} 条不通过明细见上方表格。）")
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

        # 阅读说明原先放在报告最前面,把真正的结论和明细挤到下面,改成附录
        lines.append("## 附：这份报告怎么读")
        lines.append("")
        lines.append("- **检查项**：本次核对的内容（如资格要求、投标保证金、签字盖章等）")
        lines.append("- **要求**：招标文件里是怎么规定的（并标注条款出处）")
        lines.append("- **实际**：你的投标文件里目前是什么情况（并标注所在位置）")
        lines.append("- **状态**：✅ 通过 / ❌ 不通过（必须改）/ ⚠️ 需注意（建议确认）/ ⚪ 未评估（需重新检查）")
        lines.append("- **说明**：这一项的具体解释与修改建议")
        lines.append("")

        lines.append(f"---")
        from core.settings import get_settings
        lines.append(f"*报告由 {get_settings().app_name} 自动生成*")

        return "\n".join(lines)

    def _to_html(self, data: dict, project_name: str, report_time: str = "") -> str:
        import re
        from html import escape as _esc

        md_content = self._to_markdown(data, project_name, report_time)

        def _inline(text: str) -> str:
            """行内格式: **粗体** + 状态着色。"""
            t = _esc(text)
            t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
            for word, cls in (("❌ fail", "fail"), ("✅ pass", "pass"), ("⚠️ warning", "warning"), ("⚪ unknown", "unknown")):
                t = t.replace(word, f'<span class="{cls}">{word}</span>')
            return t

        html_parts = [
            "<!DOCTYPE html>",
            "<html><head><meta charset='utf-8'>",
            f"<title>检查报告 - {_esc(project_name)}</title>",
            "<style>",
            "body { font-family: 'Microsoft YaHei','PingFang SC','Hiragino Sans GB',sans-serif;"
            " max-width: 1180px; margin: 0 auto; padding: 24px; color: #1f2937; line-height: 1.75; }",
            "h1 { color: #1a56db; border-bottom: 2px solid #1a56db; padding-bottom: 8px; }",
            "h2 { color: #374151; margin-top: 30px; }",
            "h3 { color: #4b5563; margin-top: 22px; }",
            "table { border-collapse: collapse; width: 100%; margin: 14px 0 22px; font-size: 13px; }",
            "thead th { background: #f3f4f6; font-weight: 600; white-space: nowrap; }",
            "th, td { border: 1px solid #d1d5db; padding: 10px 12px; text-align: left;"
            " vertical-align: top; word-break: break-word; }",
            "tbody tr:nth-child(even) { background: #fafafa; }",
            "tbody td:first-child { white-space: nowrap; font-weight: 500; }",
            "ul { padding-left: 22px; } li { margin: 4px 0; }",
            ".fail { color: #dc2626; font-weight: 600; }",
            ".warning { color: #d97706; font-weight: 600; }",
            ".pass { color: #059669; font-weight: 600; }",
            ".unknown { color: #6b7280; font-weight: 600; }",
            "hr { border: none; border-top: 1px solid #e5e7eb; margin: 30px 0; }",
            "</style></head><body>",
        ]

        # markdown → HTML:把连续的表格行收拢成一张真正的 <table>。
        # 原先对每个 "| ... |" 行只输出 <tr><td>(没有 <table> 包裹、没有 <thead>,
        # 连 |---|---| 分隔行都被当成数据行),浏览器会把表格外的单元格退化成
        # 紧凑的内联文字 —— 这就是"检查项/要求/实际/状态/说明 列项太紧凑"的原因。
        table_rows: list[str] = []
        list_items: list[str] = []

        def flush_table() -> None:
            if not table_rows:
                return
            head, body = table_rows[0], table_rows[1:]
            html_parts.append("<table><thead>" + head + "</thead><tbody>")
            html_parts.extend(body)
            html_parts.append("</tbody></table>")
            table_rows.clear()

        def flush_list() -> None:
            if list_items:
                html_parts.append("<ul>" + "".join(list_items) + "</ul>")
                list_items.clear()

        for line in md_content.split("\n"):
            stripped = line.strip()
            is_table_line = len(stripped) > 1 and stripped.startswith("|") and stripped.endswith("|")
            if is_table_line and re.fullmatch(r"\|[\s:|-]+\|", stripped):
                continue  # 表格分隔行不进表格
            if is_table_line:
                flush_list()
                tag = "th" if not table_rows else "td"
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                table_rows.append("<tr>" + "".join(f"<{tag}>{_esc(c)}</{tag}>" for c in cells) + "</tr>")
                continue
            flush_table()
            if stripped.startswith("### "):
                flush_list(); html_parts.append(f"<h3>{_inline(stripped[4:])}</h3>")
            elif stripped.startswith("## "):
                flush_list(); html_parts.append(f"<h2>{_inline(stripped[3:])}</h2>")
            elif stripped.startswith("# "):
                flush_list(); html_parts.append(f"<h1>{_inline(stripped[2:])}</h1>")
            elif stripped.startswith("- "):
                list_items.append(f"<li>{_inline(stripped[2:])}</li>")
            elif stripped.startswith("---"):
                flush_list(); html_parts.append("<hr>")
            elif stripped:
                flush_list(); html_parts.append(f"<p>{_inline(stripped)}</p>")
        flush_table()
        flush_list()
        html_parts.append("</body></html>")
        return "\n".join(html_parts)
