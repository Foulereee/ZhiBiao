from __future__ import annotations

"""标书正文规范化规则（元语言清理 / 承诺口径抽取 / 占位符识别）。

为什么单独抽出这个模块：
- 这三类规则被「生成后处理」和「导出前门禁」两处复用，写在 generate.py 里会
  形成循环引用，写在 content_cleaner.py 里又会让导出侧依赖生成侧。
- 规则本身要能单测，不依赖 DB / LLM。

背景（实测，见 端头及超前支护技术研究与应用.docx）：
1. 元语言：模型把提示词要求写进了正文 ——「本章旨在…」「供评标委员会逐项核查打分」
   实测 113 处，其中「本章旨在」51 处，几乎每章第一段都是。
2. 承诺口径漂移：同一份标书里质保期出现 12 个月 / 24 个月 / 36 个月 / 三年 四种说法；
   投标有效期出现 90 / 120 / 180 日历天三种；售后到场时间出现 24h / 2h / 48h / 72h。
   这是国内评标最容易被判「实质性内容前后不一致」而否决投标的点。
3. 占位符：专利号 ZL202310XXXXXX.X、业绩「某煤矿」被当成正文写进标书。
"""

import re

# ────────────────────────── 1. 元语言清理 ──────────────────────────

# 章首元语言：以「本章/本节」开头，接一个"说明性"动词
_META_LEAD = re.compile(
    r"^\s*(?:本章|本节|本篇|本部分|下章)\s*(?:节|部分)?\s*"
    r"(?:旨在|将|拟|围绕|针对|为|是|主要|首先|内容|涵盖|系统|聚焦|从)"
)

# 强元语言短语：出现即说明这句话是在对评委"解说"而不是在写投标内容
_META_PHRASES = (
    "本章旨在", "本节旨在", "本章将", "本章拟", "本章围绕", "本章为",
    "本章主要", "本章内容", "本章首先", "本章聚焦", "本章系统",
    "供评标委员会", "供评委", "为评标委员会", "为评委",
    "逐项核查", "逐项评分", "逐项打分", "评委可以据此打分",
    "评审依据", "评分依据", "便于评委", "方便评委",
    "清晰、可比", "客观、可追溯",
    "本章内容不涉及", "将在后续章节", "后续章节分别列明", "各下级章节将在",
)

# 允许保留"本章"的合法用法（正文里确实会用到，不要误删）
_META_KEEP = ("本章约定", "本章所述", "本章未尽事宜", "本章未列明", "本章另有约定")


def _is_meta_sentence(sent: str) -> bool:
    s = sent.strip()
    if not s:
        return False
    if any(k in s for k in _META_KEEP):
        return False
    hits = sum(1 for p in _META_PHRASES if p in s)
    if hits >= 2:
        return True
    if hits >= 1 and re.search(r"(本章|本节)", s):
        return True
    return False


_SENT_SPLIT = re.compile(r"(?<=[。！？；])")


def _trim_clause(text: str) -> str:
    """把 '…实质内容，供评标委员会逐项核查打分：' 里的元语言尾巴切掉，保留前半段。

    - 整句都是元语言（"本章旨在…"）→ 返回空串（整句丢弃）
    - 前半段是实质内容 → 只切掉元语言尾巴
    """
    if not _is_meta_sentence(text):
        return text
    pos = min((text.find(p) for p in _META_PHRASES if p in text), default=-1)
    if pos <= 0:
        return ""
    cut = max(text.rfind("，", 0, pos), text.rfind("、", 0, pos))
    if cut < 0:
        return ""
    prefix = text[:cut].rstrip("，、 ")
    # 前缀太短（如"此外，"）不足以独立成句，就整句丢弃
    return prefix if len(prefix) >= 12 else ""


def _strip_meta_from_line(line: str) -> str:
    """从一行里摘掉元语言；尽量保留同一行里的实质内容。"""
    line = strip_reviewer_clauses(line)
    if not any(p in line for p in _META_PHRASES):
        return line
    parts = _SENT_SPLIT.split(line)
    if len(parts) <= 1:
        return _trim_clause(line)
    return "".join(r for r in (_trim_clause(p) for p in parts) if r.strip())


# ── 第二类元语言：向评委解释文档用途的尾句 ─────────────────────────
# 实测（物业服务项目导出件）残留 23 处，形态都是
#   "……，供评标委员会核验。" / "……，便于评委核实业绩真实性。"
#   "……，为评标委员会按评分标准打分提供依据。"
# 这类句子不含"本章/本节"，句级判定抓不到；但它们是把"这份材料是给谁看的"
# 写进了正文，正式投标文件里应当直接陈述事实，而不是向评委解说。
# 这里按"逗号 + 供/便于/为 + 评委类称谓 + 到下一个逗号或句号为止"整段切除。
# 注意不要把"亦为评标委员会……的基础前提"这类句中论证一起切掉 —— 那是实质理由，
# 不是向评委解说，所以连接词里不含"亦"。
_REVIEWER_CLAUSE_RE = re.compile(
    r"[，,；;]\s*(?:以|可|能)?\s*(?:供|便于|方便|为)\s*"
    r"(?:评标委员会|评审委员会|评委|招标人代表|采购人代表|贵方|贵单位)"
    r"[^。；，,]*"
)


def strip_reviewer_clauses(text: str) -> str:
    """切掉"……，供评标委员会核验。"这类向评委解释用途的尾句。"""
    if not text or not text.strip():
        return text
    out_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        # 表格行、标题行不处理（表格里的"供评委"多为列名，动了会破坏结构）
        if stripped.startswith("|") or stripped.startswith("#"):
            out_lines.append(line)
            continue
        new = _REVIEWER_CLAUSE_RE.sub("", line)
        if new != line:
            new = re.sub(r"[，,、]\s*([。；;])", r"\1", new)
            new = re.sub(r"([。；;])\1+", r"\1", new)
        out_lines.append(new)
    return "\n".join(out_lines)


def strip_meta_language(text: str, keep_head_paragraphs: int = 3) -> str:
    """删掉正文里的元语言（"本章旨在…""供评委逐项核查打分"）。

    只做**句级**处理，不做整段删除 —— 早期版本对章首段落直接整段丢弃，
    结果把"本公司就授权代表身份及投标报价作出如下书面承诺，供评标委员会逐项核查
    打分："这种"实质内容 + 元语言尾巴"的段落一起删了，实测丢正文 1.2 万字。
    现在按句子切：
      1. 一句话里同时出现"本章/本节"+元语言短语，或含 ≥2 个元语言短语 → 判断为元语言；
      2. 元语言句里若有实质前缀（如"…作出如下书面承诺，"）→ 只切掉尾巴；
      3. 整句都是元语言 → 丢弃。
    `keep_head_paragraphs` 仅在开头若干段做一次元语言短语密度检查，用于兜住
    "整段无句号的元语言堆砌"，不再做整段删除。
    """
    if not text or not text.strip():
        return text

    kept: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        # 标题行、表格行不参与清理
        if stripped.startswith("|") or stripped.startswith("#"):
            kept.append(line)
            continue

        cleaned = _strip_meta_from_line(line)
        if cleaned.strip():
            kept.append(cleaned)

    out = "\n".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # 元语言句被删后可能留下"。。"或因断句产生的孤立标点
    out = re.sub(r"(?<=[。！？；])[。！？；]+", "", out)
    out = re.sub(r"[，、]\s*。", "。", out)
    return out.strip()


# ────────────────────────── 2. 承诺口径抽取 ──────────────────────────

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100, "千": 1000,
    "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5, "陆": 6, "柒": 7,
    "捌": 8, "玖": 9, "拾": 10, "佰": 100, "仟": 1000,
}
_CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
# 数字 token 必须包含 十/百/千，否则"三十六个月"会被切成"六"→ 误报 6 个月
_CN_NUMCHARS = tuple(_CN_DIGITS.keys())


def cn_to_int(s: str) -> int | None:
    """把中文数字转成整数。支持 一/十/十二/二十/二十四/三十六/一百/一百二十。

    存在的意义：标书里同一承诺经常一半写"二十四个月"一半写"24个月"，
    不做归一化就会把"口径一致"误判成"冲突"。
    """
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if not all(ch in _CN_DIGITS for ch in s):
        return None
    total, section, has_digit = 0, 0, False
    for ch in s:
        if ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            total += (section or 1) * unit
            section = 0
        else:
            section = _CN_DIGITS[ch]
            has_digit = True
    result = total + section
    return result or (0 if has_digit else None)


# ────────────────── 2b. 金额大小写一致性（元/万元级错误） ──────────────────
# 招标文件解读实测把"投标保证金捌万元整"记成了"人民币捌万元整（80.00元）"——
# 小写少了一万倍。大写金额才是法律上的有效表述，所以以小写为准去纠正是错的，
# 必须反过来用大写修正小写。这个错值会显示在解读页，用户抄到保证金凭证上
# 就是实质性偏差，所以入库前统一纠一次。

_CN_MONEY_BIG = {"万": 10000, "亿": 100000000}
_CN_MONEY_ALL = set("零壹贰叁肆伍陆柒捌玖拾佰仟万亿")


def cn_money_to_float(s: str) -> float | None:
    """解析大写金额：捌万元整 → 80000.0，壹佰贰拾叁万肆仟伍佰陆拾柒元 → 1234567.0。"""
    s = re.sub(r"^人民币\s*", "", (s or "").strip())
    s = re.sub(r"(元整|元|整)$", "", s)
    if not s or not all(ch in _CN_MONEY_ALL for ch in s):
        return None
    total = section = number = 0.0
    for ch in s:
        digit = _CN_DIGITS.get(ch)
        if ch in _CN_MONEY_BIG:
            total += (section + number) * _CN_MONEY_BIG[ch]
            section = number = 0.0
        elif digit in (10, 100, 1000):
            section += (number or 1) * digit
            number = 0.0
        elif digit is not None:
            number = float(digit)
    return total + section + number


_CN_AMT_PAIR_RE = re.compile(
    r"([人民币\s]*[零壹贰叁肆伍陆柒捌玖拾佰仟万亿]{2,}(?:元整|元))"
    r"\s*[（(]\s*[￥¥]?\s*([\d,]+(?:\.\d+)?)\s*(万元|万|元)?\s*[)）]"
)


def fix_cn_amount_pairs(text: str) -> str:
    """修正"大写金额（小写金额）"里小写与大写不符的情况。"""
    if not text or "元" not in text:
        return text

    def sub(m: re.Match) -> str:
        cn, raw, unit = m.group(1), m.group(2), m.group(3) or "元"
        want = cn_money_to_float(cn)
        if want is None:
            return m.group(0)
        try:
            got = float(raw.replace(",", ""))
        except ValueError:
            return m.group(0)
        if unit in ("万元", "万"):
            got *= 10000
        if abs(want - got) < 0.01:
            return m.group(0)
        return f"{cn}（￥{want:,.2f}元）"

    return _CN_AMT_PAIR_RE.sub(sub, text)


def fix_cn_amounts_in(obj, depth: int = 0):
    """递归修正嵌套结构（dict/list/str）里所有金额大小写不一致。"""
    if depth > 8:
        return obj
    if isinstance(obj, str):
        return fix_cn_amount_pairs(obj)
    if isinstance(obj, dict):
        return {k: fix_cn_amounts_in(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fix_cn_amounts_in(v, depth + 1) for v in obj]
    return obj


_NUM_TOKEN = rf"(\d+(?:\.\d+)?|[{''.join(_CN_NUMCHARS)}]{{1,6}})"

# 单位分类：同类单位之间才做数值比较
_UNIT_KIND = {
    "月": "dur", "个月": "dur", "周年": "dur", "年": "dur",
    "日历天": "day", "天": "day", "日": "day", "个日历天": "day",
    "小时": "time", "个小时": "time", "分钟": "time", "工作日": "wday", "个工作日": "wday",
    "kN": "force", "KN": "force", "千牛": "force",
}

# 类别 → (显示名, 关键词, 允许的单位种类, 关键词附近的搜索半宽)
COMMITMENT_SPECS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], int]] = {
    "warranty": ("质保期/质量保证期", ("质量保证期", "质保期", "保修期", "免费质保", "质保"), ("dur",), 22),
    "bid_validity": ("投标有效期", ("投标有效期", "报价有效期", "投标文件有效期", "有效期", "保持有效"), ("day",), 24),
    "service_period": ("服务期/工期", ("服务期", "工期", "履约期限", "交货期", "交付期"), ("dur", "day"), 18),
    "onsite_time": ("故障到场时限", ("到达现场", "抵达现场", "到场", "赶到"), ("time", "wday"), 26),
    "response_time": ("故障响应时限", ("响应时间", "响应时限", "内响应", "小时内响应", "分钟内响应", "予以响应"), ("time", "wday"), 26),
    "work_resistance": ("工作阻力", ("工作阻力",), ("force",), 18),
    "initial_support": ("初撑力", ("初撑力",), ("force",), 18),
}

_UNIT_ALT = "|".join(sorted(_UNIT_KIND, key=len, reverse=True))
_NUM_UNIT_RE = re.compile(rf"{_NUM_TOKEN}\s*({_UNIT_ALT})")

# 否定语境：这些词出现在数值**前面**时，该数值描述的不是本项承诺。
# 例："质保期结束后两年内备品备件供应" 里的"两年"是备件供应期，不是质保期；
#     不做过滤会把 24 个月质保误报成和 12 个月冲突。
_NEG_CONTEXT = ("结束后", "期满后", "届满后", "到期后", "以后", "之后", "过期后")

# 行业参照：数值前出现这些词，说明讲的是市场行情/行业惯例，不是本公司承诺。
# 实测"较行业内普遍的质保期12个月…响应速度提升50%"把行业值当成了我们的质保期。
_MARKET_REF = (
    "行业", "普遍", "常规", "通常", "一般", "市场", "同类产品", "同类设备",
    "竞争对手", "友商", "国内主流", "业界",
)

# 干扰词：出现在「关键词」与「数值」**之间**时，说明这个数值挂在别的名词上。
# 例："配件供应保障期不少于十年" —— 十年是供应保障期，不是质保期。
_INTERFERENCE = (
    "保障期", "供应期", "使用寿命", "寿命", "使用期", "有效期", "供货期",
    "库存", "备件", "年消耗", "质保金", "疲劳",
)

# 句子分隔符：关键词与数值跨句时直接丢弃（同一承诺不会跨句表述）
_SENT_BOUNDARY = "。；！？\n"
# 数值在关键词**之前**时，中间出现逗号说明它们分属不同分句
# 例："使用寿命不低于8年，质保期内…" 里的 8 年不是质保期
_PRE_BOUNDARY = "。；！？，、\n"

# 类别 → 必须出现的连接词（gap 为空时不要求）。
# 用来压掉"服务期"这类关键词附近大量无关周期的误报：
#   "服务期内每十五日开展一次专项巡检" / "安装工期由 20 天压缩至 15 天" 都不是服务期承诺。
_REQUIRED_CONNECTOR: dict[str, tuple[str, ...]] = {
    "service_period": ("不少于", "不低于", "不超过", "为"),
}


def _to_comparable(kind: str, num: str, unit: str) -> str | None:
    """归一化成可比较的字符串：时长→月/天/分钟，力→kN。"""
    n = cn_to_int(num)
    if n is None:
        return None
    uk = _UNIT_KIND.get(unit)
    if uk == "dur":
        months = n * 12 if unit in ("年", "周年") else n
        return f"{months}个月"
    if uk == "day":
        return f"{n}天"
    if uk == "wday":
        return f"{n}个工作日"
    if uk == "time":
        minutes = n * 60 if unit in ("小时", "个小时") else n
        return f"{minutes}分钟"
    if uk == "force":
        return f"{n}kN"
    return None


def iter_commitment_hits(text: str, kind: str):
    """逐处产出某个承诺类别的命中：(归一化取值, 上下文片段, 位置)。

    抽成独立生成器是为了让"生产用的冲突扫描"和"调参用的调试脚本"
    走同一套过滤逻辑 —— 否则调参时看到的精度和线上不一致。
    """
    if not text or kind not in COMMITMENT_SPECS:
        return
    _, keywords, allowed_kinds, half = COMMITMENT_SPECS[kind]
    for kw in keywords:
        for km in re.finditer(re.escape(kw), text):
            lo, hi = max(0, km.start() - half), min(len(text), km.end() + half)
            window = text[lo:hi]
            best = None  # (distance, value, seg, pos)
            for um in _NUM_UNIT_RE.finditer(window):
                num, unit = um.group(1), um.group(2)
                if _UNIT_KIND.get(unit) not in allowed_kinds:
                    continue
                val = _to_comparable(kind, num, unit)
                if not val:
                    continue
                # ⓪ 日期误读：`X月Y日` 里的 Y 是"几号"，不是"Y 天"的时长。
                # 实测"投标有效期至2026年5月12日届满"被读成"投标有效期 12 天"，
                # 与真正的"90 天"一起报成矛盾 —— 纯属误报，必须掐掉。
                if unit in ("日", "天"):
                    _pre3 = window[max(0, um.start() - 3): um.start()].rstrip()
                    if _pre3.endswith("月"):
                        continue
                # ① 否定语境：数值前 10 字内出现"结束后/期满后…"
                pre = window[max(0, um.start() - 10): um.start()]
                if any(neg in pre for neg in _NEG_CONTEXT):
                    continue
                # ①' 行业参照：数值挂在"行业普遍/常规/通常/同类产品"上时，
                # 描述的是市场行情而不是本公司的承诺。
                # 例："较行业内普遍的质保期12个月、响应时间4小时方案，响应速度提升50%"
                # —— 12 个月是行业水平，不是我们的质保期，报成矛盾是误报。
                _pre_market = window[max(0, um.start() - 22): um.start()]
                if any(mk in _pre_market for mk in _MARKET_REF):
                    continue
                # ② 同句 + 干扰词：关键词与数值必须同句，中间不能挂着别的名词
                num_s, num_e = lo + um.start(), lo + um.end()
                if num_s >= km.end():
                    gap = text[km.end():num_s]
                    if any(ch in gap for ch in _SENT_BOUNDARY):
                        continue
                else:
                    gap = text[num_e:km.start()]
                    if any(ch in gap for ch in _PRE_BOUNDARY):
                        continue
                if any(t in gap for t in _INTERFERENCE):
                    continue
                # ③ 连接词要求：gap 非空时必须出现指定连接词
                need = _REQUIRED_CONNECTOR.get(kind)
                if need and gap.strip() and not any(c in gap for c in need):
                    continue
                dist = abs(num_s - km.start())
                seg = text[max(0, num_s - 40): num_e + 40].replace("\n", " ")
                if best is None or dist < best[0]:
                    best = (dist, val, seg, num_s)
            if best:
                yield best[1], best[2], best[3]


def extract_commitments(text: str) -> dict[str, dict[str, list[str]]]:
    """抽取全文里各类承诺的取值分布。

    做法：围绕每个关键词开一个 ±half 的窗口，在窗口里找 `数值+单位`，
    取**离关键词最近**的那个（最近的才是这句话真正承诺的值）。
    这样"48小时内响应，72小时内到达现场处理"里，响应取 48 小时、到场取 72 小时，
    不会互相串味。

    返回 {类别: {归一化取值: [原句, ...]}}。
    取值只有 1 种 → 口径一致；≥2 种 → 前后矛盾，导出前必须拦下。
    """
    found: dict[str, dict[str, list[str]]] = {}
    if not text:
        return found
    for kind in COMMITMENT_SPECS:
        for val, seg, _pos in iter_commitment_hits(text, kind):
            found.setdefault(kind, {}).setdefault(val, []).append(seg)
    return found


def scan_commitment_conflicts(text: str) -> list[dict]:
    """返回冲突清单：[{kind, label, values, examples}]，只含取值 ≥2 的类别。"""
    conflicts: list[dict] = []
    for kind, values in extract_commitments(text).items():
        if len(values) < 2:
            continue
        label = COMMITMENT_SPECS.get(kind, (kind,))[0]
        conflicts.append({
            "kind": kind,
            "label": label,
            "values": sorted(values.keys(), key=lambda v: (len(v), v)),
            "examples": {v: segs[:2] for v, segs in values.items()},
        })
    conflicts.sort(key=lambda c: -len(c["values"]))
    return conflicts


# ────────────────────────── 3. 占位符 ──────────────────────────

# 必须由投标人填真实数据的项，模型只能留可检索占位，不能编造
PLACEHOLDER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("专利号占位", r"ZL?\d{4}\d{2}X{2,}[0-9X.]*"),
    ("专利号通配", r"\b[A-Z]{2}\d{4,}X{3,}"),
    ("业绩虚构", r"某(?:煤矿|公司|集团|单位|企业|医院|学校|电厂|矿)"),
    ("图片占位", r"此处需插入图片"),
    ("空待填", r"[\[【]\s*(?:待填|待补充|待生成|TBD|TODO)\s*[\]】]"),
    ("金额空值", r"\|\s*[—–]\s*\|"),
    ("未替换占位", r"【[^】]{0,20}(?:待填|请填|需填|未提供)[^】]{0,20}】"),
    # 由 build_chapter_system_prompt 要求模型输出的"待填标记"：这是**合规**占位，
    # 导出前必须被替换，但不算虚假响应，所以单独成一类。
    ("待填标记", r"\{\{\s*待填\s*[:：][^}]{0,30}\}\}"),
)

# 这些占位是"平台有意留给用户替换"的提示（插图位置、待填标记）或语义有歧义的
# 符号（表格里的"—"有时表示"无偏差/不适用"），只作为提示、不阻断导出。
# 其余占位（编造的专利号、"某煤矿"这类虚构业绩名）属于虚假响应，硬拦。
SOFT_PLACEHOLDER_KINDS: frozenset[str] = frozenset({
    "图片占位", "待填标记", "金额空值", "空待填", "未替换占位",
})

# 生成失败的痕迹。这些文本一旦落库/导出，等于把"这一章没写出来"直接交给评委。
FAILED_CONTENT_MARKERS: tuple[str, ...] = (
    "本章正文未能生成",
    "内容生成失败",
    "生成失败",
    "【数据依赖章节】",
    "请上传相关附件后重新生成",
)


def find_placeholders(text: str) -> list[dict]:
    """返回 [{kind, count, samples}]，用于导出前门禁与前端清单。"""
    out: list[dict] = []
    if not text:
        return out
    for kind, pat in PLACEHOLDER_PATTERNS:
        ms = list(re.finditer(pat, text))
        if not ms:
            continue
        out.append({
            "kind": kind,
            "count": len(ms),
            "samples": [text[max(0, m.start() - 40): m.end() + 40].replace("\n", " ")
                        for m in ms[:3]],
        })
    return out


def find_failed_markers(text: str) -> list[str]:
    """返回正文里出现的"生成失败"痕迹。"""
    return [m for m in FAILED_CONTENT_MARKERS if m in (text or "")]


# ────────────────────────── 4. 导出前门禁 ──────────────────────────

# 投标文件必须包含的章节（招标文件第六章"投标文件格式"的通行清单）。
# 第三位 hard=True 表示"缺失即可认定为投标文件不完整"的核心四件套；
# 其余只作提示 —— 实测某物业服务项目（山西工程实验技术学院）根本不设
# "商务响应"章节，硬拦会把它正常拦住，属于误判。
REQUIRED_CHAPTER_KEYWORDS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("投标函", ("投标函",), True),
    ("法定代表人身份证明", ("法定代表人身份证明", "法人身份证明"), True),
    ("开标一览表/报价表", ("开标一览表", "报价一览表", "投标报价表", "报价明细", "投标总价"), True),
    ("授权委托书", ("授权委托书", "授权书"), False),
    ("资格证明文件", ("资格证明", "资格审查", "资质证明"), False),
    ("技术方案/服务方案", ("技术方案", "服务方案", "技术部分", "实施方案"), False),
    ("商务响应", ("商务响应", "商务部分", "商务条款", "商务标"), False),
    ("售后服务", ("售后服务", "服务承诺", "质保", "质量承诺"), False),
)

# 立项门槛：单章字数低于此值视为"没写"
MIN_ACCEPTABLE_CHAPTER_CHARS = 80

# 生成范围 -> 该范围下**不适用**的章节（既不硬拦也不提示）。
# 为什么需要：用户那个项目是"技术标独立成册"（config.selected_structure_type=
# "technical"，structure_template 只有 technical 一节），它按定义**就不该**有
# 投标函、法定代表人身份证明、开标一览表/报价表 —— 而上面的硬清单无条件要求
# 这三项，结果技术标独立成册的项目**永远被 409 拦住**，除了强制导出没有出路。
# 这也违背 outlineMode='standalone-technical' 的硬约束：技术标独立成册
# 时"不得加入商务/资信、投标函、授权委托书等非技术章节"
# （见 chapter_attrs.OUTLINE_MODE_ALLOWED_ATTRS 的同款定义）。
_MODE_EXCLUDED_CHAPTERS: dict[str, tuple[str, ...]] = {
    "response-file": (),
    "partial": (),
    "standalone-technical": (
        "投标函", "法定代表人身份证明", "开标一览表/报价表",
        "授权委托书", "资格证明文件", "商务响应",
    ),
    "standalone-business": ("技术方案/服务方案", "售后服务"),
}


def scan_bid_document(
    chapters: list[dict],
    check_commitments: bool = True,
    outline_mode: str = "response-file",
) -> dict:
    """导出前全量体检。返回可直接驱动门禁与前端提示的结构。

    chapters: [{"id","title","content","is_parent"?, "word_count"?}, ...]

    分两档严重度：
      hard —— 硬阻断（强制覆盖才可以导出）：生成失败的章节、缺必选章节、
              占位符（编造的专利号/业绩/金额空值）
      soft —— 需人工确认：跨章承诺口径冲突
    """
    hard: list[dict] = []
    soft: list[dict] = []

    empty_chapters: list[str] = []
    failed_chapters: list[str] = []
    thin_chapters: list[str] = []
    all_text_parts: list[str] = []

    for ch in chapters or []:
        if not isinstance(ch, dict):
            continue
        title = str(ch.get("title") or "").strip() or "(未命名)"
        content = ch.get("content") or ""
        if not content.strip():
            empty_chapters.append(title)
            continue
        all_text_parts.append(content)
        marks = find_failed_markers(content)
        if marks:
            failed_chapters.append(f"{title}（{marks[0]}）")
        elif len(content.strip()) < MIN_ACCEPTABLE_CHAPTER_CHARS:
            thin_chapters.append(title)

    if failed_chapters:
        hard.append({
            "kind": "生成失败章节",
            "detail": f"{len(failed_chapters)} 章正文是失败提示，不能作为投标内容导出",
            "items": failed_chapters[:20],
        })
    if empty_chapters:
        hard.append({
            "kind": "空章节",
            "detail": f"{len(empty_chapters)} 章正文为空",
            "items": empty_chapters[:20],
        })
    if thin_chapters:
        soft.append({
            "kind": "内容过短章节",
            "detail": f"{len(thin_chapters)} 章正文字数不足 {MIN_ACCEPTABLE_CHAPTER_CHARS} 字",
            "items": thin_chapters[:20],
        })

    titles = [str(ch.get("title") or "") for ch in chapters or [] if isinstance(ch, dict)]
    joined_titles = "\n".join(titles)
    missing_hard: list[str] = []
    missing_soft: list[str] = []
    _excluded = set(_MODE_EXCLUDED_CHAPTERS.get(
        str(outline_mode or "response-file"), ()))
    for label, keys, is_hard in REQUIRED_CHAPTER_KEYWORDS:
        if label in _excluded:
            continue  # 该生成范围下本就不该有此章节（如技术标独立成册不含投标函）
        if not any(k in joined_titles for k in keys):
            (missing_hard if is_hard else missing_soft).append(label)
    if missing_hard:
        hard.append({
            "kind": "缺必要章节",
            "detail": "以下投标文件核心章节未出现在目录中，缺项通常直接按无效投标处理",
            "items": missing_hard,
        })
    if missing_soft:
        soft.append({
            "kind": "可能缺少的章节",
            "detail": "以下章节未在目录中出现；若招标文件未要求可不处理",
            "items": missing_soft,
        })

    full_text = "\n".join(all_text_parts)
    placeholders = find_placeholders(full_text)
    blocking_ph = [p for p in placeholders if p["kind"] not in SOFT_PLACEHOLDER_KINDS]
    if blocking_ph:
        hard.append({
            "kind": "占位符/伪数据",
            "detail": "正文中存在编造的专利号/业绩/未替换占位，导出后会被原样提交",
            "items": [f"{p['kind']} × {p['count']}" for p in blocking_ph],
            "samples": [s for p in blocking_ph for s in p["samples"][:2]][:6],
        })
    soft_ph = [p for p in placeholders if p["kind"] in SOFT_PLACEHOLDER_KINDS]
    if soft_ph:
        soft.append({
            "kind": "待人工补录",
            "detail": "以下位置需要人工替换（插图位置 / 待填标记 / 空金额），导出后请务必逐处处理",
            "items": [f"{p['kind']} × {p['count']}" for p in soft_ph],
            "samples": [s for p in soft_ph for s in p["samples"][:1]][:4],
        })

    conflicts: list[dict] = []
    if check_commitments and full_text:
        conflicts = scan_commitment_conflicts(full_text)
        # 加一句人工判断提示。实测两类情况长得一样：
        #   真矛盾：同一台设备的工作阻力写成 280kN / 3200kN / 42000kN；
        #           同一份标书的质保期写成 12/24/36 个月。
        #   合规差异：物业服务项目里"突发安全事件 5 分钟到场""一般报修 30 分钟到场"
        #           "水电故障 20 分钟到场"分属不同服务类别，本来就不该统一。
        # 这两种机器判不开，所以只提示、不阻断，并把原句附上供人工核对。
        for c in conflicts:
            c["hint"] = (
                "请核对原句：若这些取值分属不同服务类别/故障等级（如不同等级故障的"
                "响应时限），可忽略；若针对同一标的的同一指标，必须统一。"
            )
        if conflicts:
            soft.append({
                "kind": "承诺口径不一致",
                "detail": ("同一事项在全书出现多种说法，评标时可能按最不利于投标人的口径认定。"
                           "请逐条核对下方原句，确认属于真矛盾、还是不同类别各有标准。"),
                "items": [f"{c['label']}：{' / '.join(c['values'])}" for c in conflicts],
                "samples": [s for c in conflicts for s in list(c["examples"].values())[0][:1]][:6],
            })

    return {
        "ok": not hard,
        "blockers": hard,
        "warnings": soft,
        "chapter_count": len(chapters or []),
        "total_chars": len(full_text),
        "commitment_conflicts": conflicts,
    }