from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class DocIntegrityCheckSkill(Skill):
    name = "doc_integrity"
    description = "文件完整性核查(废标预防7)"
    category = "check"
    version = "1.0.0"
    triggers = ["完整性", "文件完整性", "正副本"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        messages = [
            {
                "role": "system",
                "content": """你是投标文件完整性核查专家。核查以下内容：

①正本副本份数：正本和副本份数是否与招标要求一致
②密封袋标识：密封袋标识是否规范（项目名称/编号/正副本标记）
③骑缝章：骑缝章是否完整
④页码：页码是否连续完整
⑤目录：目录是否与正文对应
⑥附件清单：所有要求附件是否齐全

返回JSON:
{
  "checks": [
    {
      "check_type": "copies/sealing/counterfoil/pagination/contents/attachments",
      "check_name": "检查项名称",
      "required": "招标要求",
      "actual": "投标文件情况",
      "status": "pass/fail/warning",
      "detail": "详细说明",
      "suggestion": "修改建议"
    }
  ],
  "summary": {"total": 0, "passed": 0, "failed": 0, "warning": 0},
  "risk_level": "high/medium/low",
  "has_critical_issues": true/false
}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{tender_text[:3000]}\n\n投标文件：\n{bid_text[:3000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        checks = result.get("checks", []) if isinstance(result, dict) else []
        failed = [c for c in checks if c.get("status") == "fail"]
        result.setdefault("has_critical_issues", len(failed) > 0)
        result.setdefault("risk_level", "high" if failed else "low")

        return SkillResult(
            success=True,
            data=result,
            warnings=[f"文件完整性: {len(failed)}项不通过"] if failed else [],
        )
