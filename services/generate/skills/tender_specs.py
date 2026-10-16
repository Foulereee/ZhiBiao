"""按标的物抽取技术规格 —— 根治"参数张冠李戴"。

## 为什么需要这个

实测（唐安煤矿端头及超前支护项目，招标文件 67510 字）生成的标书里：

    #41 端头联排液压支架技术路线  写"初撑力不低于12000kN、工作阻力不低于16000kN"
    #46 关键技术创新点分析        写端头支架"立柱DH(31.5)-835/160S、7758kN/10000kN"
    #42 超前联排液压支架技术路线  写超前支架"立柱缸径φ280/φ200、每组8根、7758kN/10000kN"

12000/16000 与 DH(31.5)-835/160S 在招标文件里**一次都没出现过**（是模型编的）；
φ280/φ200 + 7758/10000 是**端尾支架**的参数，被抄到了超前支架上。

根因不是"模型不听话"，而是招标文件第五章技术规格书里**同时存在 6 组不同的
初撑力/工作阻力**，分属 3 个标的物的「整架表」与「立柱表」：

    端头联排液压支架  整架 10048kN/12500kN   单柱 502kN/683kN   立柱 20根/组 Φ160/Φ140
    超前联排液压支架  整架  8000kN/12500kN   单柱 502kN/784kN   立柱 16根/组 Φ160/Φ140
    中置式大阻力端尾支架 整架 7758kN/10000kN 单柱 1939kN/2500kN 立柱  8根/组 φ280/φ200

而引擎把整份招标文件无差别塞给每一章，模型只能靠猜。修法是**按标的物切段**：
抽取每个设备自己的参数表，生成某设备的章节只注入该设备的段落，
再在生成后用确定性后处理把跑偏的数值改回锁定值。

## 抽取策略

1. 确定性抽取（首选）：技术要求小节标题 → 按位置切段 → 表格行解析。
   普通工业品招标文件的结构高度一致（"X、设备名技术要求"+"1.设备名基本参数"），
   实测本项目 3 个设备 14 项整架参数 + 5 项单柱参数全部抽对。
2. LLM 兜底：结构不是这个套路时（服务类、工程类、非标项目），让模型只做
   "把技术规格书里的设备与参数列出来"这一件事，且**只许照抄**。
3. 都失败：返回空，上层退化为"禁止模型给设备数值、一律用占位符"，
   宁可留空也不许编造。
"""

from __future__ import annotations

import difflib
import logging
import re

logger = logging.getLogger(__name__)

# ── 参数名词表（长名在前，避免"工作阻力"吃掉"支架工作阻力"）────────────────
PARAM_NAMES = [
    "最大不可拆卸件重量", "最大运输外形尺寸", "可适应巷道左右高差", "侧推油缸最大行程",
    "伸缩梁行程", "推移千斤顶行程", "移架步距", "泵站压力", "底板平均比压", "对底板比压",
    "平均支护强度", "支护强度", "支架工作阻力", "工作阻力", "初撑力", "支架高度",
    "支架宽度", "支架长度", "支架重量", "整组支架重量", "支架数量", "操作方式",
    "操纵方式", "缸径/柱径", "缸径/杆径", "缸径", "柱径", "行程", "数量",
    "推溜力/移架力", "推力/拉力", "截深", "型式",
    "额定电压", "额定功率", "处理能力", "设计压力", "设计温度", "材质", "规格型号",
]
_PARAM_RE = re.compile("|".join(re.escape(p) for p in PARAM_NAMES))
_UNITS = (r"根/组|kN|KN|kg|Kg|KG|mm|MM|MPa|Mpa|MPA|吨|组|架|m|t|T|%|米|千瓦|kW|"
          r"V|kV|A|kW·h|r/min|m3/h|m³/min|t/h|人|日|天|月|年")

_DEV_CLS = r"(?:支架|设备|机组|系统|装置|主机|车辆|泵站|机器人|变压器|开关|传感器|风机|水泵|皮带机|掘进机|采煤机)"
_DEV_NAME = rf"[\u4e00-\u9fa5A-Za-z0-9]{{2,24}}?{_DEV_CLS}"
_SEC_RE = re.compile(
    rf"(?:\d+(?:\.\d+)?)?\s*[、.]?\s*({_DEV_NAME})\s*"
    rf"(基本参数|主要技术参数|技术参数|性能参数|结构参数|立柱与千斤顶|主要部件技术要求|技术要求)"
)
_DOC_LIST_RE = re.compile(
    r"(?:招标内容|招标范围|采购内容|标的物|采购清单|货物清单)[^\n]{0,40}?[:：](.{0,420})"
)
_DOC_TOK_RE = re.compile(rf"^[\u4e00-\u9fa5A-Za-z0-9]{{2,24}}?{_DEV_CLS}$")

# 招标内容整句会被当成设备名（"招标内容主要为研发应用端头联排液压支架"），
# 因为它确实"以支架结尾"。用长度增量 + 动词/结构词把它挡掉。
_DOC_TOKEN_BAD_WORDS = (
    "内容", "主要", "包括", "所需", "划分", "标段", "范围", "本招标", "以及", "及其",
    "负责", "提供", "完成", "详见", "如下", "上述", "本次", "其中", "用于", "配套",
)
# 别名比规范名最多长这么多字（"中置式大阻力端尾支架" vs "端尾支架" = +6）
_ALIAS_LEN_SLACK = 6

_MODIFIERS = ("中置式", "大阻力", "液压", "联排", "新型", "智能", "自动", "高效", "式", "型")

_NUMPART = r"[ΦφØ]?\d+(?:\.\d+)?"
_NUMSEQ = (
    rf"[≤≥<>≈~～±]?\s*{_NUMPART}"
    rf"(?:\s*[～~\-—至/、*×x]\s*{_NUMPART})*"
    rf"(?:\s*±\s*\d+(?:\.\d+)?\s*%|\s*%|\s*±\s*\d+(?:\.\d+)?)?"
)
_NUM_UNIT_RE = re.compile(rf"({_NUMSEQ})\s*({_UNITS})(?![a-zA-Z])")
# 表格里 "P=25MPa" 紧跟在数值后面会顶掉单位边界（"10048kNP=25MPa"），先摘掉
_P_ANNOT_RE = re.compile(r"[Pp]\s*[=＝]\s*[\d.]+\s*(?:MPa|Mpa|MPA|mpa)?")


def _lcs_len(a: str, b: str) -> int:
    return difflib.SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b)).size


def _core(name: str) -> str:
    s = name
    for w in _MODIFIERS:
        s = s.replace(w, "")
    return s or name


def same_device(a: str, b: str) -> bool:
    """两个名字是否指同一个标的物（端尾支架 == 中置式大阻力端尾支架）。"""
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    if _lcs_len(a, b) >= max(3, len(a) - 1):
        return True
    ca, cb = _core(a), _core(b)
    return _lcs_len(ca, cb) >= max(2, len(ca) - 1)


def _normalize(section: str) -> str:
    """合掉 PDF 抽取引入的断行断字（"推移 千斤 顶" -> "推移千斤顶"）。"""
    return re.sub(r"\s+", "", section)


def _doclist_tokens(text: str) -> list[str]:
    toks: list[str] = []
    for m in _DOC_LIST_RE.finditer(text):
        for raw in re.split(r"[、,，;；。\n：:()（）]", m.group(1)):
            raw = re.sub(r"\d+\s*(?:架|组|台|套|根)?\s*$", "", raw.strip()).strip()
            if _DOC_TOK_RE.match(raw):
                toks.append(raw)
    return toks


def discover_devices(text: str) -> dict[str, list[str]]:
    """返回 {规范设备名: [别名...]}，规范名取最长形式。"""
    heads = [m.group(1) for m in _SEC_RE.finditer(text)]
    if not heads:
        return {}
    groups: dict[str, list[str]] = {}
    for n in sorted(set(heads), key=len, reverse=True):
        for c in groups:
            if same_device(n, c):
                groups[c].append(n)
                break
        else:
            groups[n] = [n]
    doc = _doclist_tokens(text)
    out: dict[str, list[str]] = {}
    for canon, al in groups.items():
        best = canon
        for t in doc:
            if any(w in t for w in _DOC_TOKEN_BAD_WORDS):
                continue
            if len(t) > len(canon) + _ALIAS_LEN_SLACK:
                # "招标内容主要为研发应用端头联排液压支架" 只是碰巧包含规范名，
                # 不是它的另称 —— 长度增量是最好用的判据
                continue
            if same_device(t, canon):
                al.append(t)
                if len(t) > len(best):
                    best = t
        out[best] = sorted(set(al) | {canon, best}, key=len, reverse=True)
    return out


def extract_params(section: str) -> dict[str, str]:
    """抽 (参数名 -> 内容)。

    坑：端尾表格第 10 行的备注列写着"推移千斤顶行程900"，朴素的"取第一个"
    会把 推移千斤顶行程 抽成"10移架步距800mm"。所以用严格数值序列 + 多候选打分：
    值里含别的参数名 → 淘汰；无数字 → 淘汰；优先带单位、优先短。
    """
    sec = _P_ANNOT_RE.sub("", _normalize(section))
    cand: dict[str, list[tuple[int, str]]] = {}
    for m in _PARAM_RE.finditer(sec):
        tail = re.sub(r"^[\s|:：]+", "", sec[m.end(): m.end() + 40])
        um = _NUM_UNIT_RE.match(tail)
        if um:
            val, score = (um.group(1) + um.group(2)).strip(), 0
        else:
            nm = re.match(r"^(\d+(?:\.\d+)?)", tail)
            if not nm:
                continue
            val, score = nm.group(1), 2
        if not val or len(val) > 32 or not re.search(r"\d", val):
            continue
        if _PARAM_RE.search(val):
            continue
        cand.setdefault(m.group(0), []).append((score, val))
    out: dict[str, str] = {}
    for name, lst in cand.items():
        lst.sort(key=lambda x: (x[0], len(x[1])))
        out[name] = lst[0][1]
    return out


_ALIAS_SUFFIX_SWAPS = (
    ("联排液压支架", "联排支架"),
    ("联排液压支架", "液压支架"),
    ("联排液压支架", "支架"),
    ("液压支架", "支架"),
    ("联排支架", "支架"),
)


def expand_aliases(canon: str, aliases=None) -> list[str]:
    """给规范名补上正文里常见的简写。

    为什么必须要：招标文件里的规范名是"端头联排液压支架"，而正文大量写
    "端头支架"。别名表里没有简写，参数强制统一时就认不出这句话在讲哪台
    设备，只能沿用"上一个提到的设备"——实测第 44 章因此写出
    "端头支架长度10m"（应为 14.5m）、"整架初撑力分别为8000kN与8000kN"
    （端头应为 10048kN）。
    """
    out: list[str] = []
    for name in [canon] + [str(a) for a in (aliases or [])]:
        name = (name or "").strip()
        if not name:
            continue
        out.append(name)
        for src, dst in _ALIAS_SUFFIX_SWAPS:
            if src in name:
                out.append(name.replace(src, dst))
    seen, uniq = set(), []
    for a in out:
        if a not in seen and len(a) >= 2:
            seen.add(a)
            uniq.append(a)
    # 长别名优先：匹配时更精确的排在前面，避免"端头支架"先命中而漏掉全称
    return sorted(uniq, key=len, reverse=True)


def _pillar_summary(pillar_section: str) -> dict[str, str]:
    """立柱（单柱）参数用定点正则，比通用部件切段可靠得多。"""
    sec = _P_ANNOT_RE.sub("", _normalize(pillar_section))
    out: dict[str, str] = {}
    m = re.search(r"立柱[^0-9]{0,16}?数量?(\d+)\s*根/组", sec)
    if m:
        out["立柱数量"] = m.group(1) + "根/组"
    m = re.search(r"缸径\s*[/／]?\s*柱径\s*([Φφ]?[\d.]+\s*/\s*[Φφ]?[\d.]+)", sec)
    if m:
        out["立柱缸径柱径"] = m.group(1)
    else:
        m = re.search(r"缸径\s*([Φφ]?[\d.]+\s*/\s*[Φφ]?[\d.]+)", sec)
        if m:
            out["立柱缸径"] = m.group(1)
        m = re.search(r"柱径\s*([Φφ]?[\d.]+\s*/\s*[Φφ]?[\d.]+)", sec)
        if m:
            out["立柱柱径"] = m.group(1)
    m = re.search(r"初撑力\s*(\d+(?:\.\d+)?)\s*kN", sec)
    if m:
        out["单柱初撑力"] = m.group(1) + "kN"
    m = re.search(r"工作阻力\s*(\d+(?:\.\d+)?)\s*kN", sec)
    if m:
        out["单柱工作阻力"] = m.group(1) + "kN"
    m = re.search(r"型式\s*([双单]伸缩式?)", sec)
    if m:
        out["立柱型式"] = m.group(1)
    return out


# 整架级参数统一命名（避免"工作阻力"与"支架工作阻力"各存一份）
_WHOLE_KEYS = {
    "初撑力": "整架初撑力", "工作阻力": "整架工作阻力", "支架工作阻力": "整架工作阻力",
    "支架高度": "支架高度", "支架宽度": "支架宽度", "支架长度": "支架长度",
    "支护强度": "支护强度", "平均支护强度": "支护强度",
    "对底板比压": "底板比压", "底板平均比压": "底板比压",
    "泵站压力": "泵站压力", "移架步距": "移架步距",
    "最大运输外形尺寸": "最大运输外形尺寸", "最大不可拆卸件重量": "最大不可拆卸件重量",
    "支架重量": "整组支架重量", "整组支架重量": "整组支架重量", "支架数量": "数量",
    "操作方式": "操作方式", "操纵方式": "操作方式", "可适应巷道左右高差": "巷道高差",
    "伸缩梁行程": "伸缩梁行程", "侧推油缸最大行程": "侧推油缸行程",
    "规格型号": "规格型号", "材质": "材质", "额定功率": "额定功率", "额定电压": "额定电压",
}

# 这些是"必须锁死的核心指标"——抽不到就说明确定性抽取失败了
CORE_WHOLE = ("整架初撑力", "整架工作阻力")
CORE_ANY = CORE_WHOLE + ("支架高度", "移架步距", "整组支架重量")

# 抓"张冠李戴"用：哪些词一出现就说明这段在讲某个具体设备
DEVICE_HINT_WORDS = ("支架", "设备", "机组", "系统", "装置", "主机", "车辆", "泵站")


def extract_device_specs(text: str) -> dict[str, dict]:
    """确定性抽取：{设备: {整架, 单柱, aliases, section_text}}。"""
    groups = discover_devices(text)
    if not groups:
        return {}
    hits = list(_SEC_RE.finditer(text))
    sections: list[tuple[str, str, str]] = []
    for i, h in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else min(len(text), h.end() + 3000)
        sections.append((h.group(1), h.group(2), text[h.start():end]))

    out: dict[str, dict] = {}
    for canon, aliases in groups.items():
        base: dict[str, str] = {}
        pillar_sec = ""
        raw_parts: list[str] = []
        for dev, kind, body in sections:
            if not any(same_device(dev, a) for a in aliases):
                continue
            raw_parts.append(body)
            if kind in ("基本参数", "主要技术参数", "技术参数", "性能参数") and not base:
                base = extract_params(body)
            elif kind == "立柱与千斤顶" and not pillar_sec:
                pillar_sec = body
        whole: dict[str, str] = {}
        for k, v in base.items():
            key = _WHOLE_KEYS.get(k)
            if key and key not in whole and v:
                whole[key] = v
        pillar = _pillar_summary(pillar_sec) if pillar_sec else {}
        section_text = "\n".join(p.strip() for p in raw_parts if p.strip())[:7000]
        out[canon] = {
            "aliases": expand_aliases(canon, aliases),
            "整架": whole,
            "单柱": pillar,
            "section_text": section_text,
            "source": "tender_rule",
        }
    return out


SPEC_LLM_PROMPT = """你是招投标技术规格结构化提取引擎。请从【技术规格书原文】里把**每个标的物**的参数列出来。

铁律：
1. **只许照抄**原文出现的数值，一个都不许推算、补充、四舍五入或"合理估计"。
2. 原文没给的参数，直接不输出该项；绝对不要用别的设备的参数填补，也不要写区间猜测值。
3. 严格区分标的物：原文只给了 A 设备的参数时，绝不能把 A 的参数写进 B。
4. 同一设备若有"整架参数"和"单柱/单件参数"两套，分别放进 整架 和 单柱。
5. 数值保留原文的单位（如 "10048kN"、"Φ160/Φ140"、"2500-4200mm"）。

返回 JSON：
{
  "devices": [
    {"name": "设备规范名称", "aliases": ["原文里出现过的其它叫法"],
     "整架": {"整架初撑力": "10048kN", "整架工作阻力": "12500kN", "支架高度": "2500-4200mm"},
     "单柱": {"立柱数量": "20根/组", "立柱缸径柱径": "Φ160/Φ140", "单柱初撑力": "502kN"}}
  ]
}"""


async def build_device_specs(tender_text: str, llm=None) -> dict[str, dict]:
    """确定性抽取优先，失败或不全时用 LLM 兜底。返回 {设备: {...}}。"""
    if not tender_text:
        return {}
    specs = extract_device_specs(tender_text)
    ok = {
        dev: s for dev, s in specs.items()
        if all(k in s["整架"] for k in CORE_WHOLE)
    }
    if ok:
        logger.info("[设备规格] 确定性抽取命中 %d/%d 个设备", len(ok), len(specs))
        return specs

    if llm is None:
        return specs

    # LLM 兜底：只喂技术规格书那一段，避免模型从别的章节"脑补"
    window = _spec_window(tender_text)
    try:
        res = await llm.collect_json(
            messages=[
                {"role": "system", "content": SPEC_LLM_PROMPT},
                {"role": "user", "content": f"【技术规格书原文】\n{window[:12000]}"},
            ],
            temperature=0.0,
        )
    except Exception as e:  # pragma: no cover
        logger.warning("[设备规格] LLM 兜底失败: %s", e)
        return specs
    if not isinstance(res, dict):
        return specs
    out: dict[str, dict] = {}
    for d in res.get("devices") or []:
        if not isinstance(d, dict) or not d.get("name"):
            continue
        out[str(d["name"])] = {
            "aliases": expand_aliases(str(d["name"]), d.get("aliases")),
            "整架": {str(k): str(v) for k, v in (d.get("整架") or {}).items() if v},
            "单柱": {str(k): str(v) for k, v in (d.get("单柱") or {}).items() if v},
            "section_text": "",
            "source": "tender_llm",
        }
    logger.info("[设备规格] LLM 兜底得到 %d 个设备", len(out))
    return out or specs


def _spec_window(text: str) -> str:
    """截取技术规格书正文，别把投标人须知/评分办法喂进去。"""
    m = re.search(r"第[五六七八]章\s*技术(?:规格|要求)", text)
    if m:
        return text[m.start():]
    m = re.search(r"技术(?:规格书|要求|规格)", text)
    if m:
        return text[max(0, m.start() - 200):]
    return text[-24000:]


# ── 章节 → 设备归属 ────────────────────────────────────────────────────
def detect_chapter_devices(title: str, body: str, specs: dict[str, dict]) -> list[str]:
    """判断某一章在讲哪些标的物。标题优先，其次正文首段。"""
    if not specs:
        return []
    hits: list[str] = []
    for dev, s in specs.items():
        names = [dev] + list(s.get("aliases") or [])
        if any(n and n in (title or "") for n in names):
            hits.append(dev)
    if hits:
        return hits
    head = (body or "")[:1200]
    for dev, s in specs.items():
        names = [dev] + list(s.get("aliases") or [])
        if any(n and n in head for n in names):
            hits.append(dev)
    return hits


def render_spec_block(dev: str, spec: dict, *, with_section: bool = True) -> str:
    """把一个设备的唯一参数渲染成可注入提示词的文本。"""
    lines = [f"【{dev}】唯一技术参数（招标文件原文，全书凡涉及本设备必须一字不差引用）"]
    whole = spec.get("整架") or {}
    if whole:
        lines.append("  整架参数：" + "；".join(f"{k}={v}" for k, v in whole.items()))
    pillar = spec.get("单柱") or {}
    if pillar:
        lines.append("  立柱/单件参数：" + "；".join(f"{k}={v}" for k, v in pillar.items()))
    if with_section and spec.get("section_text"):
        lines.append("  招标文件原文段落（只许据此撰写，不得跨设备引用）：")
        lines.append("  " + spec["section_text"].replace("\n", "\n  ")[:3000])
    return "\n".join(lines)


def render_all_specs_table(specs: dict[str, dict]) -> str:
    """全书设备参数总表 —— 用于"本章涉及多台设备"时的横向对标。"""
    if not specs:
        return ""
    keys: list[str] = []
    for s in specs.values():
        for k in (s.get("整架") or {}):
            if k not in keys:
                keys.append(k)
    if not keys:
        return ""
    out = ["| 参数 | " + " | ".join(specs.keys()) + " |", "|" + "---|" * (len(specs) + 1)]
    for k in keys:
        row = [k]
        for s in specs.values():
            row.append((s.get("整架") or {}).get(k, "—"))
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)