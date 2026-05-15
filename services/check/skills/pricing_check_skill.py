from __future__ import annotations

import re

from core.skill_engine.base import Skill, SkillContext, SkillResult


class PricingCheckSkill(Skill):
    name = "pricing_check"
    description = "报价算术核查(废标预防4)"
    category = "check"
    version = "1.0.0"
    triggers = ["报价", "算术", "价格核查"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")
        max_price = ctx.parameters.get("max_price")

        checks = []

        check_limit = self._check_price_limit(bid_text, max_price)
        checks.append(check_limit)

        check_case = self._check_upper_lower_case(bid_text)
        checks.extend(check_case)

        check_arithmetic = self._check_arithmetic(bid_text)
        checks.extend(check_arithmetic)

        check_safe_range = self._check_safe_range(bid_text, max_price)
        checks.append(check_safe_range)

        failed = [c for c in checks if c.get("status") == "fail"]
        return SkillResult(
            success=True,
            data={
                "checks": checks,
                "summary": {
                    "total": len(checks),
                    "passed": len([c for c in checks if c["status"] == "pass"]),
                    "failed": len(failed),
                    "warning": len([c for c in checks if c["status"] == "warning"]),
                },
                "risk_level": "high" if failed else "low",
            },
        )

    def _check_price_limit(self, bid_text: str, max_price: float | None) -> dict:
        if max_price is None:
            return {"check_type": "price_limit", "status": "warning", "detail": "未提供最高限价"}
        total_match = re.search(r"投标总价[：:]\s*([\d,，.]+)\s*万?元?", bid_text)
        if total_match:
            total = float(total_match.group(1).replace(",", "").replace("，", ""))
            if total > max_price:
                return {"check_type": "price_limit", "status": "fail", "detail": f"投标总价{total}万超过最高限价{max_price}万"}
            return {"check_type": "price_limit", "status": "pass", "detail": f"投标总价{total}万未超过限价{max_price}万"}
        return {"check_type": "price_limit", "status": "warning", "detail": "未找到投标总价"}

    def _check_upper_lower_case(self, bid_text: str) -> list[dict]:
        checks = []
        pattern = r"([零一二三四五六七八九十百千万亿]+万?元)\s*[（(]\s*([\d,，.]+)\s*[）)]"
        for match in re.finditer(pattern, bid_text):
            chinese_amount = match.group(1)
            digit_amount = match.group(2)
            checks.append({
                "check_type": "upper_lower_case",
                "status": "pass",
                "detail": f"大写:{chinese_amount} 小写:{digit_amount}元 (需人工确认一致)",
            })
        if not checks:
            checks.append({"check_type": "upper_lower_case", "status": "warning", "detail": "未检测到大小写金额对照"})
        return checks

    def _check_arithmetic(self, bid_text: str) -> list[dict]:
        checks = []
        row_pattern = r"(\d+)\s*[、．.]\s*(.+?)\s+([\d,，.]+)\s*[×xX]\s*([\d,，.]+)\s*=\s*([\d,，.]+)"
        for match in re.finditer(row_pattern, bid_text):
            try:
                unit_price = float(match.group(3).replace(",", "").replace("，", ""))
                quantity = float(match.group(4).replace(",", "").replace("，", ""))
                expected = unit_price * quantity
                actual = float(match.group(5).replace(",", "").replace("，", ""))
                if abs(expected - actual) > 0.01:
                    checks.append({
                        "check_type": "arithmetic",
                        "status": "fail",
                        "detail": f"第{match.group(1)}项: {unit_price}×{quantity}={expected:.2f}≠{actual}",
                    })
            except ValueError:
                continue
        if not checks:
            checks.append({"check_type": "arithmetic", "status": "pass", "detail": "算术验算通过(或未检测到算术行)"})
        return checks

    def _check_safe_range(self, bid_text: str, max_price: float | None) -> dict:
        if max_price is None:
            return {"check_type": "safe_range", "status": "warning", "detail": "未提供限价，无法判断安全区间"}
        if max_price == 0:
            return {"check_type": "safe_range", "status": "warning", "detail": "限价为0，无法计算安全区间"}
        total_match = re.search(r"投标总价[：:]\s*([\d,，.]+)", bid_text)
        if total_match:
            total = float(total_match.group(1).replace(",", "").replace("，", ""))
            ratio = total / max_price
            if 0.95 <= ratio <= 0.98:
                return {"check_type": "safe_range", "status": "pass", "detail": f"报价在限价{ratio:.1%}，处于安全区间(95%-98%)"}
            elif ratio < 0.95:
                return {"check_type": "safe_range", "status": "warning", "detail": f"报价仅为限价{ratio:.1%}，低于95%安全线"}
            else:
                return {"check_type": "safe_range", "status": "fail", "detail": f"报价为限价{ratio:.1%}，超过98%"}
        return {"check_type": "safe_range", "status": "warning", "detail": "未找到投标总价"}
