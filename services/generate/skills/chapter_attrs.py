# -*- coding: utf-8 -*-
"""章节属性（attr）与内容处理模式（content_mode）。

【为什么要有这个模块】

本平台原来把三件互相正交的事压成了一个枚举
（`config.selected_structure_type` = bid_letter/qualification/technical/
commercial/service），于是出现两个无法回答的问题：

  "我选了技术标，那这份标书里到底哪些章是技术标？"
  "选了技术标，为什么商务、报价、投标函的章节还在？"

这三件事其实是正交的，拆成三层：

  ① 投标范围 bidSection —— 投哪个标段/标包，**与标类型无关**；
  ② 生成范围 outlineMode —— 完整投标文件 / 技术文件独立成册 / 商务标独立成册；
  ③ 每章属性 attr(7值) + content_mode(5值) —— **"这章到底是不是技术标"的唯一判定**，
     由 AI 给初值、用户可逐条改、**程序用映射表强制推导 content_mode**。

本模块只做 ② 的"范围断言"和 ③ 的"分类 + 强制推导"，把主观的 UI 选择变成
可判定、可校验、可被拒绝的数据。

【为什么默认不采用"非 ai-generate 就不让 AI 写"】

严格模式下只跑 `content_mode=='ai-generate'` 的叶子，
报价节点因此完全不由 AI 生成。本平台的情况不同：分项报价明细表是靠
`{待填:单价}`/`{待填:合价}` 占位符由 AI 生成表格骨架的，直接停写会**删掉已有内容**。
按本项目的红线（宁可漏改不可错改），这里默认仍生成全部叶子，只把
content_mode 作为分类/校验信息；确需严格模式时用环境变量
BMP_STRICT_CONTENT_MODE=1 打开，才改为只生成 ai-generate 叶子。
"""

import os
import re

# 一级目录属性：7 个取值，与对标项目 OUTLINE_ATTRIBUTES 完全一致
ATTRS = ["通用", "商务/资信", "技术", "其他", "目录", "报价", "业绩"]

# 叶子内容处理模式：5 个取值，与对标项目 CONTENT_MODES 完全一致
CONTENT_MODES = [
    "ai-generate",       # 由 AI 生成正文
    "template-fill",     # 填招标文件给的投标格式表格
    "directory-generate",  # 目录页
    "manual-fill",       # 人工填写（报价等）
    "other",
]

# attr -> content_mode 强制映射（对标项目 ATTRIBUTE_CONTENT_MODE_RULES，
# 且它用 JSON-Schema if/then 强绑，违反即保存失败）
ATTR_CONTENT_MODE_RULES = {
    "商务/资信": "template-fill",
    "目录": "directory-generate",
    "报价": "manual-fill",
    "业绩": "template-fill",
    "技术": "ai-generate",
    "通用": "ai-generate",
    "其他": "other",
}

# 关键词判定：顺序即优先级。报价必须排最前 —— "分项报价明细表"同时含"报价"
# 与"表"，而"关键技术参数及报价"这类标题必须落到 报价 而不是 技术。
_ATTR_RULES = (
    ("目录", ("目录", "索引", "篇章结构")),
    ("报价", ("投标报价", "报价", "开标一览", "价格", "费用构成", "分项报价",
              "报价表", "价格表", "计价")),
    ("业绩", ("业绩", "案例", "类似项目", "供货经历", "销售业绩")),
    ("商务/资信", (
        "资格", "资信", "资质", "营业执照", "财务", "信用", "授权委托",
        "法定代表人", "商务", "投标函", "承诺函", "保证金", "社保", "纳税",
        "声明", "违约", "履约", "偏离表", "优惠条件", "付款条件", "服务期限",
        "投标有效期",
    )),
    ("技术", (
        "技术", "方案", "工艺", "设备", "参数", "性能", "质量", "质保",
        "售后", "服务", "实施", "进度", "工期", "安全", "培训", "备品备件",
        "备件", "易损件", "运维", "检验", "试验", "安装", "调试", "监测",
        "支护", "供配电", "控制", "制造", "设计", "验收", "运输", "包装",
        "研发", "开发", "可靠性", "保障措施", "团队", "组织管理", "管理机构",
        "人员配置", "风险管控", "应急",
    )),
)

# 生成范围（对标项目 outlineMode）
OUTLINE_MODES = {
    "response-file": "完整投标文件",
    "standalone-technical": "技术文件独立成册",
    "standalone-business": "商务标独立成册",
    "partial": "部分章节",
}

# 生成范围 -> 允许出现的 attr（对标项目 standalone-technical 的硬约束：
# "attr 必须为技术、content_mode 必须为 ai-generate"，
# 且"不得加入商务/资信、投标函、授权委托书等非技术章节"）
OUTLINE_MODE_ALLOWED_ATTRS = {
    "response-file": list(ATTRS),
    "partial": list(ATTRS),
    "standalone-technical": ["技术"],
    "standalone-business": ["商务/资信", "报价", "业绩", "通用", "其他"],
}

# 对标项目在技术标独立成册时明确禁止的外层总目录
FORBIDDEN_OUTER_TITLES = (
    "技术方案", "项目管理方案", "监理大纲", "施工组织设计", "技术标",
)


def strict_content_mode() -> bool:
    """是否启用"非 ai-generate 叶子不生成"的严格模式（默认关）。

    默认关是刻意的：本平台的分项报价表靠占位符由 AI 生成骨架，
    直接停写会删内容，违反"宁可漏改不可错改"。
    """
    return str(os.environ.get("BMP_STRICT_CONTENT_MODE", "")).strip().lower() in (
        "1", "true", "yes", "on",
    )


# 生成范围 -> 大纲提示词的硬约束（对标项目 outlineGenerationTaskV2 在
# standalone-technical 下的写法："attr 必须为技术、content_mode 必须为
# ai-generate"、"不得创建技术方案/项目管理方案/监理大纲/施工组织设计/技术标
# 等外层总目录，也不得加入商务/资信、投标函、授权委托书等非技术章节"）。
#
# 为什么必须有这段：平台原来的大纲提示词里硬写着"必须包含：投标函、资格审查、
# 技术方案、商务报价等基本章节"，所以**用户选了技术标，生成出来的仍然是完整
# 投标文件** —— 选择从未被落实。真实数据可证：selected_structure_type='technical'
# 的标书里 14 个一级目录有 6 个不是技术属性。
OUTLINE_MODE_PROMPT_RULES = {
    "response-file": (
        "【生成范围要求】\n"
        "本次生成范围是「完整投标文件」：按招标文件“投标文件组成/投标文件格式”"
        "的顺序生成全部章节，涵盖投标函、资格审查、技术方案、商务报价等。"
    ),
    "standalone-technical": (
        "【生成范围要求 —— 最高优先级，与其它任何要求冲突时以本条为准】\n"
        "本次生成范围是「技术文件独立成册」（即技术标单独成册），必须遵守：\n"
        "1. 只生成属于技术标的章节。每个一级目录都必须能归入技术范畴，例如"
        "技术方案与技术路线、设备技术参数与性能指标、质量与质保体系、"
        "实施与进度计划、安装调试与验收、售后技术服务与技术培训、"
        "安全与风险管控、运维与备品备件等。\n"
        "2. 【严禁】生成投标函、投标承诺、资格审查、资质证明、营业执照、"
        "财务与信用材料、业绩案例、商务报价、开标一览表、付款条件、"
        "优惠条件、保证金等非技术章节。\n"
        "3. 【严禁】创建“技术方案”“项目管理方案”“监理大纲”“施工组织设计”"
        "“技术标”这类外层总目录 —— 每个一级目录直接对应一个技术评分大项，"
        "不要再套一层总目录。\n"
        "4. 一级目录数量由招标文件里技术评分项的数量决定，不要为凑数强行拆分。"
    ),
    "standalone-business": (
        "【生成范围要求 —— 最高优先级，与其它任何要求冲突时以本条为准】\n"
        "本次生成范围是「商务标独立成册」，必须遵守：\n"
        "1. 只生成属于商务、资信与报价范围的章节，例如投标函、投标承诺、"
        "资格审查与资质证明、财务与信用材料、业绩案例、商务条款响应与偏离、"
        "付款与优惠条件、开标一览与分项报价等。\n"
        "2. 【严禁】生成技术方案、技术参数、工艺流程、实施与进度、"
        "质量与质保体系、售后技术服务等技术章节。\n"
        "3. 报价类章节只做格式与结构，具体单价、合价一律留待填占位符。"
    ),
    "partial": (
        "【生成范围要求】\n"
        "本次只生成用户选定的部分章节，不要扩展到完整的投标文件结构。"
    ),
}


def scope_requirement(selected_or_mode: object) -> str:
    """取生成范围对应的大纲硬约束文本（可直接拼进提示词）。"""
    raw = str(selected_or_mode or "").strip()
    mode = raw if raw in OUTLINE_MODE_PROMPT_RULES else outline_mode_from_selection(raw)
    return OUTLINE_MODE_PROMPT_RULES.get(mode, "")


def classify_title(title: str, content_hint: str = "") -> str:
    """按标题（必要时结合内容提示）判定一级目录属性。

    只看标题不看正文是刻意的：对标项目的 attr 也只挂在一级目录上
    （schema 里只有 root 才有且 required），子节点靠继承。
    """
    text = f"{title or ''} {content_hint or ''}"
    if not text.strip():
        return "其他"
    for attr, kws in _ATTR_RULES:
        for kw in kws:
            if kw in text:
                return attr
    return "通用"


def enforce_content_mode(attr: str) -> str:
    """由 attr 强制推导 content_mode —— 不允许两者不一致。"""
    return ATTR_CONTENT_MODE_RULES.get(attr, "other")


def outline_mode_from_selection(selected: object) -> str:
    """把平台已有的"选择模板"映射成对标项目的"生成范围"。

    这是本次改造的关键一步：`selected_structure_type` 以前既被当成
    "投标范围"又被当成"结构骨架"，其实它表达的是**生成范围**。
    映射：
      all/完整 -> response-file（完整投标文件）
      technical -> standalone-technical（技术文件独立成册）
      commercial -> standalone-business（商务标独立成册）
      其它单个模板 -> partial
    """
    if isinstance(selected, (list, tuple, set)):
        vals = [str(v) for v in selected]
    else:
        vals = [str(selected or "")]
    vals = [v.strip() for v in vals if str(v).strip()]
    if not vals or "all" in vals or len(vals) > 1:
        return "response-file"
    only = vals[0]
    if only == "technical":
        return "standalone-technical"
    if only == "commercial":
        return "standalone-business"
    return "partial"


def _walk(nodes, level=1, out=None):
    out = out if out is not None else []
    for n in nodes or []:
        if isinstance(n, dict):
            out.append((level, n))
            _walk(n.get("children"), level + 1, out)
    return out


def classify_tree(tree: dict, selected: object = None) -> dict:
    """给大纲树打上 attr / content_mode，并做范围断言。

    只改 `chapters` 下的一级节点及其后代：一级节点写 attr + content_mode，
    后代继承一级节点的 attr（对标项目也是只有一级目录带 attr），
    content_mode 逐节点独立（叶子才是真正决定生成与否的地方）。

    返回报告：各属性计数、非技术章节清单、范围断言问题、危险标题。
    """
    chapters = (tree or {}).get("chapters") or []
    outline_mode = outline_mode_from_selection(selected)
    allowed = set(OUTLINE_MODE_ALLOWED_ATTRS.get(outline_mode, ATTRS))

    flat = _walk(chapters)
    counts: dict[str, int] = {}
    top_level: list[dict] = []
    issues: list[str] = []
    non_technical: list[dict] = []
    forbidden: list[str] = []

    for level, node in flat:
        if level != 1:
            continue
        title = str(node.get("title") or "").strip()
        hint = str(node.get("description") or node.get("content_hint") or "")
        attr = str(node.get("attr") or "").strip() or classify_title(title, hint)
        if attr not in ATTRS:
            issues.append(f"一级目录「{title}」的 attr={attr!r} 不是合法取值，已回退为 其他")
            attr = "其他"
        node["attr"] = attr
        node["content_mode"] = enforce_content_mode(attr)
        counts[attr] = counts.get(attr, 0) + 1
        top_level.append({"id": node.get("id"), "title": title, "attr": attr,
                          "content_mode": node["content_mode"]})
        if attr not in allowed:
            non_technical.append({"id": node.get("id"), "title": title, "attr": attr})
        if outline_mode == "standalone-technical":
            for bad in FORBIDDEN_OUTER_TITLES:
                if title == bad:
                    forbidden.append(title)

    # 后代继承一级目录的 attr；content_mode 用自身映射（默认继承）
    for level, node in flat:
        if level == 1:
            continue
        pid = str(node.get("parent_id") or "")
        node.setdefault("content_mode", "ai-generate")
    # 用一次显式遍历把 attr 继承下去
    def inherit(nodes, parent_attr=""):
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            if parent_attr and not n.get("attr"):
                n["attr"] = parent_attr
            inherit(n.get("children"), n.get("attr") or parent_attr)

    inherit(chapters, "")

    if outline_mode == "standalone-technical" and non_technical:
        issues.append(
            f"生成范围是「技术文件独立成册」，但有 {len(non_technical)} 个一级目录"
            f"不是技术属性（{'、'.join(x['title'] for x in non_technical[:6])}"
            f"{'…' if len(non_technical) > 6 else ''}），需要确认是否剔除"
        )
    if forbidden:
        issues.append(
            f"技术标独立成册时不应出现外层总目录：{'、'.join(forbidden)}"
        )

    return {
        "outline_mode": outline_mode,
        "outline_mode_label": OUTLINE_MODES.get(outline_mode, outline_mode),
        "allowed_attrs": sorted(allowed),
        "total_top_level": len(top_level),
        "attr_counts": counts,
        "top_level": top_level,
        "non_technical": non_technical,
        "forbidden_outer_titles": forbidden,
        "issues": issues,
        "strict_content_mode": strict_content_mode(),
    }


def apply_strict_filter(tree: dict, chapters: list) -> list:
    """严格模式下按 content_mode 过滤要生成的叶子（默认不启用）。

    启用后行为与对标项目一致：只生成 content_mode=='ai-generate' 的叶子。
    """
    if not strict_content_mode():
        return chapters
    keep = []
    for ch in chapters or []:
        mode = str((ch or {}).get("content_mode") or "ai-generate")
        if mode == "ai-generate":
            keep.append(ch)
    return keep