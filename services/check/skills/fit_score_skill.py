from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult


class FitScoreSkill(Skill):
    name = "fit_score"
    description = "贴合度评分"
    category = "check"
    version = "1.0.0"
    triggers = ["贴合度", "针对性", "模板检测"]

    GENERIC_PHRASES = [
        "我司具有丰富的行业经验",
        "本公司拥有专业的技术团队",
        "我们具备完善的售后服务体系",
        "公司秉承客户至上的理念",
        "具有多年的项目实施经验",
        "拥有一流的技术实力",
        "我们将竭诚为您服务",
    ]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        tender_text = ctx.parameters.get("tender_text", "")
        bid_text = ctx.parameters.get("bid_text", "")

        generic_count = sum(1 for phrase in self.GENERIC_PHRASES if phrase in bid_text)

        messages = [
            {
                "role": "system",
                "content": f"""评估投标文件与招标文件的贴合度。

评分维度：
1. 内容贴合度(40%): 是否严格贴合招标文件要求
2. 技术方案针对性(30%): 技术方案是否针对项目场景定制
3. 评分项覆盖率(20%): 评分项是否有对应应答内容
4. 废标条款响应率(10%): 废标条款是否全部响应

已知通用套话命中: {generic_count}/{len(self.GENERIC_PHRASES)}

返回JSON:
{{
  "fit_score": 0-100,
  "dimensions": {{
    "content_fit": {{"score": 0-100, "detail": "说明"}},
    "technical_targeting": {{"score": 0-100, "detail": "说明"}},
    "scoring_coverage": {{"score": 0-100, "detail": "说明"}},
    "disqualification_response": {{"score": 0-100, "detail": "说明"}}
  }},
  "generic_phrases_found": ["发现的通用套话列表"],
  "suggestions": ["改进建议"]
}}""",
            },
            {
                "role": "user",
                "content": f"招标文件：\n{tender_text[:4000]}\n\n投标文件：\n{bid_text[:4000]}",
            },
        ]

        result = await ctx.llm.collect_json(messages=messages, temperature=0.1)
        return SkillResult(success=True, data=result)
