from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult

SELFCHECK_ITEMS = [
    {
        "category": "资质文件核查",
        "items": [
            {"id": "SC-01", "content": "所有资质证书有效期覆盖投标截止日", "check_skill": "qualification_check"},
            {"id": "SC-02", "content": "证书名称与招标要求完全一致", "check_skill": "qualification_check"},
            {"id": "SC-03", "content": "三证合一/旧版分离证书匹配", "check_skill": "qualification_check"},
            {"id": "SC-04", "content": "证书扫描件清晰可辨", "check_skill": "qualification_check"},
        ],
    },
    {
        "category": "投标保证金核查",
        "items": [
            {"id": "SC-05", "content": "保证金金额与招标要求一致(精确到分)", "check_skill": "deposit_check"},
            {"id": "SC-06", "content": "缴纳形式符合要求", "check_skill": "deposit_check"},
            {"id": "SC-07", "content": "到账时间早于截止时间", "check_skill": "deposit_check"},
            {"id": "SC-08", "content": "保函有效期覆盖投标有效期+30天", "check_skill": "deposit_check"},
        ],
    },
    {
        "category": "文件完整性与签章核查",
        "items": [
            {"id": "SC-09", "content": "正本副本份数与要求一致", "check_skill": "doc_integrity"},
            {"id": "SC-10", "content": "所有要求签章页面已签章", "check_skill": "signature_check"},
            {"id": "SC-11", "content": "密封袋标识规范", "check_skill": "doc_integrity"},
            {"id": "SC-12", "content": "骑缝章完整", "check_skill": "signature_check"},
        ],
    },
    {
        "category": "技术与报价核查",
        "items": [
            {"id": "SC-13", "content": "所有★▲强制性参数已响应且无负偏离", "check_skill": "mandatory_req_check"},
            {"id": "SC-14", "content": "报价算术无误(单价×数量=合价)", "check_skill": "pricing_check"},
            {"id": "SC-15", "content": "投标总价未超过最高限价", "check_skill": "pricing_check"},
            {"id": "SC-16", "content": "大写金额与小写金额一致", "check_skill": "pricing_check"},
        ],
    },
    {
        "category": "有效期与合规核查",
        "items": [
            {"id": "SC-17", "content": "投标有效期≥招标要求天数", "check_skill": "validity_check"},
            {"id": "SC-18", "content": "保函有效期覆盖投标有效期", "check_skill": "validity_check"},
            {"id": "SC-19", "content": "CA证书在有效期内", "check_skill": "validity_check"},
            {"id": "SC-20", "content": "跨章节数据一致性校验通过", "check_skill": "consistency_check"},
        ],
    },
]


def _is_check_passed(skill_result: dict) -> bool:
    if not skill_result:
        return False
    if skill_result.get("has_critical_issues"):
        return False
    risk_level = skill_result.get("risk_level", "")
    if risk_level in ("high", "critical"):
        return False
    summary = skill_result.get("summary", {})
    if isinstance(summary, dict) and summary.get("failed", 0) > 0:
        return False
    return True


class SelfcheckListSkill(Skill):
    name = "selfcheck_list"
    description = "废标自查清单(综合预防)"
    category = "check"
    version = "1.0.0"
    triggers = ["自查", "废标自查", "提交前检查"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        check_results = ctx.parameters.get("check_results", {})
        all_passed = True

        categories = []
        for category_def in SELFCHECK_ITEMS:
            cat_items = []
            for item in category_def["items"]:
                skill_result = check_results.get(item["check_skill"])
                if skill_result:
                    status = "pass" if _is_check_passed(skill_result) else "fail"
                else:
                    status = "pending"
                cat_items.append({
                    "id": item["id"],
                    "content": item["content"],
                    "status": status,
                    "check_skill": item["check_skill"],
                })
                if status != "pass":
                    all_passed = False
            categories.append({"category": category_def["category"], "items": cat_items})

        total_items = sum(len(c["items"]) for c in categories)
        passed_items = sum(1 for c in categories for i in c["items"] if i["status"] == "pass")

        return SkillResult(
            success=True,
            data={
                "categories": categories,
                "all_passed": all_passed,
                "can_submit": all_passed,
                "total_items": total_items,
                "passed_items": passed_items,
            },
        )
