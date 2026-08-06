"""Check skill data 归一化工具。

不同 check skill 返回的 data 字典 schema 不统一：
- compliance: `{"items": [...], "total_requirements": ...}`
- pricing: `{"checks": [...], "summary": {...}, "risk_level": ...}`
- consistency: `{"checks": [...], "summary": {...}, "inconsistencies": [...]}`
- disqualification: `{"items": [...], "missing": ..., "risk_level": ...}`

提供 `normalize_check_findings` 把任意 skill data 归一化为：

    {
        "findings": [
            {
                "id": "...",
                "title": "...",
                "severity": "critical|warning|pass",
                "status": "pass|warning|fail",
                "detail": "...",
                "suggestion": "...",
                "raw": {...},  # 原始 item，debug 用
            },
            ...
        ],
        "summary": {"total": N, "pass": N, "warning": N, "fail": N, "source_key": "items"},
        "risk_level": "low|medium|high",
    }

供前端统一渲染。前端可以兼容老 schema（直接读 skill_data.findings 或
skill_data.items/checks）—— 本工具不影响现有 route 返回值。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 按优先级检测 skill data 字典中的 items 数组
_ITEM_KEYS: tuple[str, ...] = (
    "items",
    "checks",
    "findings",
    "results",
    "issues",
    "clauses",
    "inconsistencies",
    "duplicates",
    "missing",  # disqualification 用作 count 时跳过（count 非 list）
)

# status/severity → pass/warning/fail 归一化
_STATUS_MAP: dict[str, str] = {
    "pass": "pass", "ok": "pass", "compliant": "pass", "approved": "pass",
    "明确": "pass",
    "warning": "warning", "warn": "warning", "minor": "warning",
    "partial": "warning", "low": "warning", "medium": "warning",
    "模糊": "warning",
    "fail": "fail", "error": "fail", "critical": "fail", "high": "fail",
    "non_compliant": "fail", "rejected": "fail",
    "缺失": "fail",
}


def _normalize_status(value: Any) -> str:
    if value is None or value == "":
        return "warning"
    return _STATUS_MAP.get(str(value).lower().strip(), "warning")


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _detect_items(data: dict) -> tuple[str, list[dict]] | None:
    """从 skill data 中识别 items 数组。返回 (key, items) 或 None。"""
    for key in _ITEM_KEYS:
        items = data.get(key)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return key, items
    return None


def _extract_finding(item: dict) -> dict:
    """把一个 item 归一化为 finding。"""
    severity = _normalize_status(
        item.get("severity") or item.get("risk_level")
    )
    status = _normalize_status(
        item.get("status") or item.get("response_quality")
    )
    title = (
        item.get("title")
        or item.get("name")
        or item.get("check_type")
        or item.get("clause_content")
        or item.get("requirement")
        or item.get("description")
        or "未命名检查项"
    )
    detail = (
        item.get("detail")
        or item.get("description")
        or item.get("response_content")
        or item.get("content")
        or ""
    )
    return {
        "id": _coerce_text(item.get("id") or item.get("clause_id") or ""),
        "title": _coerce_text(title),
        "severity": severity,
        "status": status,
        "detail": _coerce_text(detail),
        "suggestion": _coerce_text(item.get("suggestion") or item.get("recommendation") or ""),
        "raw": item,
    }


def normalize_check_findings(data: Any) -> dict:
    """把任意 check skill 的 data 归一化为 findings[] 格式。

    Args:
        data: skill 返回的 data 字典（或其他类型）

    Returns:
        标准化的 dict，包含 `findings`、`summary`、`risk_level`
    """
    empty: dict = {
        "findings": [],
        "summary": {"total": 0, "pass": 0, "warning": 0, "fail": 0},
        "risk_level": "low",
    }

    if not isinstance(data, dict):
        return empty

    detected = _detect_items(data)
    if detected is None:
        # fallback: 整个 data 视为单个 finding（轻量提示）
        return {
            "findings": [_extract_finding(data)],
            "summary": {
                "total": 1,
                "pass": 0,
                "warning": 1,
                "fail": 0,
                "source_key": None,
            },
            "risk_level": "low",
        }

    key, items = detected
    findings = [_extract_finding(item) for item in items if isinstance(item, dict)]

    pass_n = sum(1 for f in findings if f["status"] == "pass")
    warn_n = sum(1 for f in findings if f["status"] == "warning")
    fail_n = sum(1 for f in findings if f["status"] == "fail")

    raw_risk = data.get("risk_level", "")
    if raw_risk in ("low", "medium", "high"):
        risk_level = raw_risk
    elif fail_n > 0:
        risk_level = "high"
    elif warn_n > 0:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "findings": findings,
        "summary": {
            "total": len(findings),
            "pass": pass_n,
            "warning": warn_n,
            "fail": fail_n,
            "source_key": key,
        },
        "risk_level": risk_level,
    }


def wrap_skill_data(data: Any) -> dict:
    """Convenience: 把 skill data 包裹成 `{raw: data, findings: ...}` 双 schema 输出。

    既保留原始 data 供老前端使用，也附加归一化 findings 供新前端使用。
    """
    if not isinstance(data, dict):
        return {"raw": data, **normalize_check_findings(data)}
    normalized = normalize_check_findings(data)
    return {**data, "findings": normalized["findings"], "_findings_summary": normalized["summary"]}
