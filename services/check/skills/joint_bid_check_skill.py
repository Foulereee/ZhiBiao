from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class JointBidCheckSkill(Skill):
    name = "joint_bid_check"
    description = "联合投标协议核查(C-19): 联合体投标协议完整性核查"
    category = "check"
    version = "1.0.0"
    triggers = ["联合投标", "联合体", "联合体协议"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        if not tender_text or not bid_text:
            return SkillResult(success=False, error="招标文件和投标文件内容不能为空")

        messages = [
            {
                "role": "system",
                "content": """你是联合投标协议核查专家。对联合体投标的协议文件进行完整性核查。

核查要点：
1. 联合体资质核查:
   - 招标文件是否允许联合体投标
   - 联合体各方是否具备相应的资质条件
   - 联合体资质等级是否符合招标要求(就低不就高原则)

2. 协议内容完整性:
   - 联合体协议是否包含所有必需方签字盖章
   - 是否明确联合体各方的分工和责任
   - 是否指定联合体牵头人
   - 是否约定各方承担的份额比例
   - 是否包含连带责任条款

3. 合规性核查:
   - 联合体各方是否单独或参与其他联合体重复投标
   - 联合体成员数量是否符合招标文件限制
   - 协议有效期是否覆盖投标及合同执行期

返回JSON:
{
  "total_checks": 数量,
  "passed": 数量,
  "failed": 数量,
  "warning": 数量,
  "checks": [
    {
      "check_type": "qualification/agreement_content/compliance",
      "check_name": "检查项名称",
      "tender_requirement": "招标文件要求",
      "bid_content": "投标文件内容",
      "status": "pass/fail/warning",
      "detail": "详细说明",
      "suggestion": "修改建议"
    }
  ],
  "consortium_info": {
    "is_consortium_bid": true/false,
    "allowed_by_tender": true/false,
    "lead_member": "牵头方名称(如能识别)",
    "member_count": 成员数量,
    "missing_signatures": ["缺少签字盖章的成员列表"]
  },
  "risk_level": "high/medium/low"
}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{tender_text[:6000]}\n\n投标文件：\n{bid_text[:6000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)

        failed = [c for c in result.get("checks", []) if c.get("status") == "fail"]
        if failed:
            result["has_critical_issues"] = True

        return SkillResult(success=True, data=result)
