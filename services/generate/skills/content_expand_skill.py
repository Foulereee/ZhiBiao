from __future__ import annotations

from core.skill_engine.base import Skill, SkillContext, SkillResult

MODE_PROMPTS = {
    "expand": {
        "instruction": "扩写以下内容，在保持原意的基础上增加细节、论据和案例，使内容更加充实丰富。",
        "temperature": 0.5,
    },
    "condense": {
        "instruction": "精简以下内容，去除冗余表述，保留核心要点，使内容更加简洁有力。",
        "temperature": 0.3,
    },
    "rewrite": {
        "instruction": "改写以下内容，调整表述方式和句式结构，保持原意不变但表达更加专业规范。",
        "temperature": 0.5,
    },
    "polish": {
        "instruction": "润色以下内容，优化语言表达，提升文字质量和专业度，修正不通顺的表述。",
        "temperature": 0.3,
    },
}


class ContentExpandSkill(Skill):
    name = "content_expand"
    description = "扩写与改写(G-07): 扩写/精简/改写/润色"
    category = "generate"
    version = "1.0.0"
    triggers = ["扩写", "改写", "精简", "润色"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        text = ctx.parameters.get("text", "")
        mode = ctx.parameters.get("mode", "polish")

        if not text:
            return SkillResult(success=False, error="待处理文本内容为空")

        if mode not in MODE_PROMPTS:
            return SkillResult(
                success=False,
                error=f"不支持的模式: {mode}，可选: {', '.join(MODE_PROMPTS.keys())}",
            )

        mode_config = MODE_PROMPTS[mode]
        word_count_target = ctx.parameters.get("word_count")
        tender_context = ctx.parameters.get("tender_context", "")

        word_count_instruction = ""
        if word_count_target:
            word_count_instruction = f"\n目标字数约{word_count_target}字。"

        context_instruction = ""
        if tender_context:
            context_instruction = f"\n\n参考招标要求：\n{tender_context[:3000]}"

        messages = [
            {
                "role": "system",
                "content": f"""你是标书内容撰写专家。{mode_config['instruction']}

要求：
1. 保持专业性和准确性
2. 内容必须针对项目实际情况，不得使用空洞的通用模板套话
3. 术语使用规范统一
4. 逻辑清晰，层次分明{word_count_instruction}

返回JSON:
{{
  "content": "处理后的文本内容",
  "word_count": 实际字数,
  "mode": "{mode}",
  "changes_summary": "主要修改说明"
}}""",
            },
            {
                "role": "user",
                "content": f"原文内容：\n{text[:6000]}{context_instruction}",
            },
        ]

        result = await ctx.llm.collect_json(
            messages=messages, temperature=mode_config["temperature"]
        )
        return SkillResult(success=True, data=result)
