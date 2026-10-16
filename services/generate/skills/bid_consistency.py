"""标书一致性引擎 —— 生成后的确定性修复。

## 为什么必须有这一层

提示词已经写过"未知数据用 {{待填}}，严禁编造"，但实测（213 章整本生成的
《文件.docx》）模型照样编造，且编得自相矛盾：

    第1章 投标函及商务承诺   "投标总报价为人民币5850000.00元（伍佰捌拾伍万元整）"
    第2章 投标函             "投标总报价为人民币伍佰柒拾伍万元整（￥5,750,000.00元）"
    第3章 投标总报价声明     "{{待填:投标总报价大写}}（￥{{待填:投标总报价小写}}元）"
    第179章 项目总报价明细    "第一期 30% 1,794,000.00 / 第二期 30% 1,794,000.00"

同一份投标函出现 585 万和 575 万两个总价，分项报价还按编造的总价算出了
1,794,000.00 —— 这属于《招标投标法》意义上的虚假响应，直接废标。
占位符本身也不统一：投标总报价 / 投标总报价金额 / 投标总报价小写 / 投标总价 /
投标总价大写 / 大写金额 六种叫法混用，人工补录时极易漏填。

**结论：凡涉及"绝对不能错"的数据，一律不交给模型自觉，改为生成后确定性改写。**
本模块只做四类可证明正确的事：替换已知错误值、删除明确不该出现的内容、
按锁定值统一参数、规范化占位符名称。每一步都留痕（ChangeLog）供用户复核。

## 作用域隔离

另一个实测病灶是"全量 Prompt 广播"：引擎把废标红线清单和招标文件摘要无差别
注入每一章，于是纯技术章 `4.5.1 行业前沿技术融合应用` 结尾在写
"投标保证金80000.00元……纸质一正二副共3份，U盘1份，胶装不装订"，
备件明细表在 12 个章节里被原样粘贴了十余遍。

修法分两头：
  - 生成时：按章节作用域只注入对应数据（见 chapter_context / tender_specs）
  - 生成后：本模块把漏进来的商务程序性句子删掉、把重复的备件大表压成一句话
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from services.generate.skills.tender_specs import (
    detect_chapter_devices,
    render_spec_block,
    same_device,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# 一、章节作用域
# ══════════════════════════════════════════════════════════════════════════

SCOPE_COMMERCIAL = "commercial"      # 投标函/报价/商务承诺/授权/偏差
SCOPE_QUALIFICATION = "qualification"  # 资格证明/营业执照/信用/资质证书
SCOPE_PERFORMANCE = "performance"    # 近三年业绩（只写历史，不写本次）
SCOPE_TECHNICAL = "technical"        # 技术方案/结构/参数/仿真/试验
SCOPE_QUALITY = "quality"            # 质量保障/检验/追溯/认证
SCOPE_WARRANTY = "warranty"          # 质保措施/质保体系
SCOPE_SCHEDULE = "schedule"          # 实施计划/进度/资源/团队
SCOPE_SERVICE = "service"            # 售后服务/培训
SCOPE_SPARE = "spare"                # 备品备件/易损件/随机附件
SCOPE_SAFETY = "safety"              # 安全/风险/应急
SCOPE_GENERAL = "general"

ALL_SCOPES = (
    SCOPE_COMMERCIAL, SCOPE_QUALIFICATION, SCOPE_PERFORMANCE, SCOPE_TECHNICAL,
    SCOPE_QUALITY, SCOPE_WARRANTY, SCOPE_SCHEDULE, SCOPE_SERVICE, SCOPE_SPARE,
    SCOPE_SAFETY, SCOPE_GENERAL,
)

# 作用域判定：按顺序匹配，先命中的赢（越具体的放前面）
_SCOPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (SCOPE_PERFORMANCE, ("业绩", "类似项目", "同类型项目", "历史项目", "已完项目",
                         "合同关键条款摘要", "付款凭证", "验收记录", "客户使用效果",
                         "发票", "使用单位", "供货业绩")),
    (SCOPE_SPARE, ("备品备件", "备件", "易损件", "随机附件", "随机标准附件",
                   "专用工具", "外购件", "外购配套")),
    (SCOPE_QUALIFICATION, ("资格", "营业执照", "资质", "信用", "失信", "认证证书",
                           "煤安", "MA证书", "安全生产许可", "体系认证", "授权书",
                           "法定代表人身份", "联合体")),
    (SCOPE_COMMERCIAL, ("投标函", "开标一览", "报价", "商务", "付款", "保证金",
                        "有效期", "优惠", "偏差表", "价格", "成本", "结算",
                        "履约及违约", "服务期限与质量")),
    (SCOPE_WARRANTY, ("质保", "保修", "三包", "售后备件保障")),
    (SCOPE_SERVICE, ("售后", "服务", "培训", "巡检", "维修", "技术支持", "回访")),
    (SCOPE_SCHEDULE, ("实施", "进度", "工期", "计划", "里程碑", "资源配置",
                      "团队", "组织", "人力资源", "物资保障", "供应周期", "物流")),
    (SCOPE_SAFETY, ("安全", "风险", "应急", "隐患", "环境", "职业健康", "消防")),
    (SCOPE_QUALITY, ("质量", "检验", "试验", "检测", "追溯", "可靠性", "寿命",
                     "认证", "合格", "工艺", "焊接", "涂装", "来料", "出厂")),
)

# 技术类章节标题里的强特征
_TECH_HINTS = ("技术", "研发", "结构", "参数", "性能", "方案", "仿真", "应力",
               "液压", "电液", "控制", "选型", "原理", "创新", "对标", "适配",
               "设计", "工况", "支护", "承载", "材料")


def classify_scope(title: str, body: str = "") -> str:
    """判定章节作用域。标题优先，标题无特征时看正文首 400 字。"""
    t = title or ""
    for scope, keys in _SCOPE_RULES:
        if any(k in t for k in keys):
            return scope
    if any(k in t for k in _TECH_HINTS):
        return SCOPE_TECHNICAL
    head = (body or "")[:400]
    for scope, keys in _SCOPE_RULES:
        if any(k in head for k in keys):
            return scope
    if any(k in head for k in _TECH_HINTS):
        return SCOPE_TECHNICAL
    return SCOPE_GENERAL


# 允许出现"招投标程序性条款"的作用域（其余作用域一律剥离）
PROCEDURAL_ALLOWED_SCOPES = frozenset({SCOPE_COMMERCIAL, SCOPE_QUALIFICATION})


# ══════════════════════════════════════════════════════════════════════════
# 二、占位符规范化
# ══════════════════════════════════════════════════════════════════════════

PH = "{{待填:%s}}"

# 同一件事的多种叫法 → 唯一规范名。人工补录时"查找替换"一次就能填完全部。
CANONICAL_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "投标总报价小写": ("投标总报价小写", "投标总报价金额", "投标总报价", "投标总价小写",
                       "投标总价", "投标报价", "投标报价金额", "总报价", "报价金额",
                       "投标报价小写"),
    "投标总报价大写": ("投标总报价大写", "投标总报价金额大写", "投标总价大写", "报价大写",
                       "大写金额", "投标报价大写", "总报价大写", "投标总报价大写金额",
                       "投标报价金额大写"),
    "不含税金额": ("不含税金额", "不含税价", "不含税报价"),
    "增值税税额": ("增值税税额", "税额", "税金", "增值税额"),
    "法定代表人姓名": ("法定代表人姓名", "法定代表人或授权代表姓名", "法人姓名",
                       "法定代表人"),
    "被授权人姓名": ("被授权人姓名", "授权代表姓名", "委托代理人姓名"),
    "统一社会信用代码": ("统一社会信用代码", "社会信用代码", "信用代码"),
    "开户银行": ("开户银行", "开户行"),
    "银行账号": ("银行账号", "账号", "帐号"),
}

_VARIANT_TO_CANON: dict[str, str] = {}
for _canon, _vs in CANONICAL_PLACEHOLDERS.items():
    for _v in _vs:
        _VARIANT_TO_CANON[_v] = _canon

_PH_RE = re.compile(r"\{\{\s*待填\s*[:：]\s*([^}]{1,40}?)\s*\}\}")


# 兜底归类规则：模型总会造出新叫法（实测造出过"投标总报价金额大写"）。
# 只靠穷举变体永远追不上，所以加一层"看名字里有什么词"的归类。
# 顺序敏感：先判"大写/小写"，再判报价类，最后才是税额/不含税。
_FUZZY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("大写", "金额大写"), "投标总报价大写"),
    (("小写",), "投标总报价小写"),
    (("不含税",), "不含税金额"),
    (("税额", "税金"), "增值税税额"),
    (("统一社会信用代码", "信用代码"), "统一社会信用代码"),
    # 只认"开户"，不能只认"银行" —— 否则"银行保函金额"会被归成"开户银行"
    (("开户",), "开户银行"),
    (("账号", "帐号"), "银行账号"),
    (("被授权人", "授权代表", "委托代理人"), "被授权人姓名"),
)


def _fuzzy_canon(name: str) -> str | None:
    if not name:
        return None
    is_price = any(k in name for k in ("报价", "总价", "价格"))
    for keys, canon in _FUZZY_RULES:
        if not any(k in name for k in keys):
            continue
        # "大写/小写/税额/不含税"这类词本身已足够定位；"账号/开户行"要限价类词防止误伤
        if canon in ("开户银行", "银行账号") and is_price:
            continue
        if canon in ("投标总报价大写", "投标总报价小写") and not is_price:
            continue
        return canon
    return None


def canonicalize_placeholders(text: str) -> tuple[str, int]:
    """把 `{{待填:投标总价}}` 之类统一成规范名。返回 (新文本, 改动数)。"""
    n = 0

    def sub(m: re.Match) -> str:
        nonlocal n
        name = m.group(1).strip()
        canon = _VARIANT_TO_CANON.get(name) or _fuzzy_canon(name)
        if canon and canon != name:
            n += 1
            return PH % canon
        return m.group(0)

    return _PH_RE.sub(sub, text or ""), n


# ══════════════════════════════════════════════════════════════════════════
# 三、报价防伪
# ══════════════════════════════════════════════════════════════════════════

# "投标总报价为人民币5850000.00元"的几种写法。
# 注意前缀要单独捕获：第一版直接把整个匹配替换成占位符，把"投标总报价为"
# 也一起删掉了，而且第二遍大写替换又匹配进刚插入的占位符里，套成
# "{{待填:{{待填:投标总报价大写}}" —— 自检当场抓到这个 bug。
_PRICE_KEY = r"(?:投标总报价|投标总价|投标报价|总报价|报价总额|合同价|中标价|报价)"
_CUR = r"(?:人民币\s*)?(?:[￥¥]\s*)?"
_AMT_NUM = rf"({_CUR})(\d[\d,]*(?:\.\d+)?)\s*(万元|万|元)"
_AMT_CN = r"(" + _CUR + r")((?:[壹贰叁肆伍陆柒捌玖拾佰仟万亿]{2,})(?:元整|元))"
_NUM_TO_CN = {0: "零", 1: "壹", 2: "贰", 3: "叁", 4: "肆", 5: "伍", 6: "陆", 7: "柒", 8: "捌", 9: "玖"}


def allowed_amounts(ledger: dict | None) -> set[str]:
    """招标文件锁定、允许在正文里出现的金额（保证金、预算、税率等）。

    这些是招标文件客观事实，不属于"编造"，不能被替换掉。
    """
    out: set[str] = set()
    if not ledger:
        return out
    blob = " ".join(
        str(x) for x in (
            [i.get("value") for i in (ledger.get("items") or []) if isinstance(i, dict)]
            + [p.get("required") for p in (ledger.get("key_params") or []) if isinstance(p, dict)]
            + list(ledger.get("prohibited") or [])
            + [ledger.get("allowed_amounts") or ""]
        )
    )
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(万元|万|元|%)", blob):
        out.add(m.group(1).replace(",", "") + m.group(2))
        out.add(m.group(1).replace(",", ""))
    return out


def strip_invented_prices(text: str, allowed: set[str] | None = None) -> tuple[str, list[str]]:
    """把编造的报价金额换成占位符。只动"报价语境"里的金额。

    实测病灶：5850000.00 / 5,750,000.00 / 伍佰捌拾伍万元整 / 1,794,000.00。
    这些都不是招标文件给的数，也不是用户给的数，全是模型自己拍的。
    """
    allowed = allowed or set()
    changes: list[str] = []

    def _ok(raw: str) -> bool:
        k = raw.replace(",", "")
        return k in allowed or (k + "元") in allowed or (k + "万元") in allowed

    def sub_num(m: re.Match) -> str:
        # 组：1=报价关键字前缀，2=货币符号，3=数字，4=单位
        num, unit = m.group(3), m.group(4)
        if _ok(num):
            return m.group(0)
        changes.append(f"报价金额 {num}{unit} → 占位符")
        return m.group(1) + m.group(2) + (PH % "投标总报价小写") + unit

    out = re.sub(rf"({_PRICE_KEY}[^\n。；]{{0,30}}?){_AMT_NUM}", sub_num, text or "")

    def sub_cn(m: re.Match) -> str:
        changes.append(f"大写报价 {m.group(3)} → 占位符")
        return m.group(1) + m.group(2) + (PH % "投标总报价大写")

    # 大写的后面常跟小写："{{待填:投标总报价大写}}（￥5,750,000.00元）" ——
    # 中间隔着占位符和括号，间距放宽到 30 字才能连上；上一版只给 12 字，
    # 结果大写换了、小写漏了（实测第 2 章）。
    out = re.sub(rf"({_PRICE_KEY}[^\n。；]{{0,30}}?){_AMT_CN}", sub_cn, out)

    # 带货币符号/"人民币"字样的金额是铁板钉钉的"钱"，与报价关键字无关也要换。
    # 注意标记**必须是必需的**：第一版把货币符号写成可选，`_CUR` 于是能匹配空串，
    # 这条规则变成了"替换文里所有数字" —— "含13%增值税"都被改成了占位符。
    def sub_cur(m: re.Match) -> str:
        num = m.group(2)
        if _ok(num):
            return m.group(0)
        changes.append(f"货币符号金额 {m.group(0).strip()} → 占位符")
        # 这里不一定在讲报价：实测命中过"注册资本不低于人民币500万元"
        # "保险金额不低于每人人民币100万元"，写成"投标总报价小写"会误导填报人，
        # 所以用中性的"金额"。
        return m.group(1) + (PH % "金额")

    out = re.sub(r"([￥¥]\s*)(\d[\d,]*(?:\.\d+)?)\s*(?:万元|万|元)?", sub_cur, out)
    out = re.sub(r"(人民币\s*)(\d[\d,]*(?:\.\d+)?)\s*(?:万元|万|元)", sub_cur, out)
    return out, changes


# 表格里的裸金额。**只认"长得像钱"的数**：有千分位，或 4 位以上且带两位小数。
# 第一版用 `\d{5,}` 兜底，结果把项目编号 2601002、银行账号 145600001018170210404、
# 疲劳寿命 100000 次全当成了报价 —— 必须收紧。
_BARE_AMT_RE = re.compile(
    r"(?<![\dA-Za-z\-])"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d{4,}\.\d{2})"
    r"(?![\dA-Za-z\-])"
)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.M)
# 这一行必须在讲钱，才允许替换（避免改到参数表/寿命表）
_MONEY_ROW_KEYS = ("报价", "单价", "合价", "金额", "总价", "费用", "税额", "价款",
                   "元", "万元", "暂估", "小计", "合计", "预算",
                   "支付", "付款", "款项", "第一期", "第二期", "第三期", "第四期")


def strip_table_amounts(text: str, allowed: set[str] | None = None) -> tuple[str, list[str]]:
    """报价表格里的裸金额换成占位符。

    实测：`| 第一期 | 货物到矿并取得MA证书后 | 30% | 1,794,000.00 | ...` ——
    这个 1,794,000.00 是按编造总价 5,980,000 算出来的 30%，属于虚假响应。
    """
    allowed = allowed or set()
    changes: list[str] = []
    lines = (text or "").split("\n")
    for i, ln in enumerate(lines):
        if not _TABLE_ROW_RE.match(ln):
            continue
        if "待填" in ln or not any(k in ln for k in _MONEY_ROW_KEYS):
            continue

        def sub(m: re.Match) -> str:
            raw = m.group(1)
            if raw.replace(",", "") in allowed:
                return raw
            changes.append(f"分项报价 {raw} → 占位符")
            return PH % "分项报价"

        lines[i] = _BARE_AMT_RE.sub(sub, ln)
    return "\n".join(lines), changes


# ══════════════════════════════════════════════════════════════════════════
# 四、算术自洽（派生数值跟着锁定值更新）
# ══════════════════════════════════════════════════════════════════════════

# 实测第 42 章："静载试验加载至工作阻力12500kN的1.2倍，即12000 kN" ——
# 强制统一把工作阻力从 10000 改成了 12500，但"即12000"是照旧值算的
# （10000×1.2=12000，12500×1.2=15000），自己和自己打架。
# 这类"由某个基数算出来"的数字必须跟着一起重算，否则改一半等于没改。
_DERIVED_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(kN|KN|MPa|mm|吨|t)\s*的\s*(\d+(?:\.\d+)?)\s*倍"
    r"([^\n。；]{0,6}?)即\s*(\d[\d,]*(?:\.\d+)?)\s*(kN|KN|MPa|mm|吨|t)"
)


def fix_derived_numbers(text: str) -> tuple[str, list[str]]:
    """重算"N倍即X"这类派生数值。"""
    changes: list[str] = []

    def sub(m: re.Match) -> str:
        base = float(m.group(1).replace(",", ""))
        times = float(m.group(3))
        stated = float(m.group(5).replace(",", ""))
        want = base * times
        if abs(stated - want) < max(0.51, want * 0.005):
            return m.group(0)
        new = f"{want:g}"
        changes.append(
            f"算术自洽：{m.group(1)}{m.group(2)} 的 {m.group(3)} 倍应为 {new}{m.group(6)}，"
            f"原文误写 {m.group(5)}{m.group(6)}"
        )
        return f"{m.group(1)}{m.group(2)}的{m.group(3)}倍{m.group(4)}即{new}{m.group(6)}"

    return _DERIVED_RE.sub(sub, text or ""), changes


# ══════════════════════════════════════════════════════════════════════════
# 五、商务程序性条款跨域剥离
# ══════════════════════════════════════════════════════════════════════════

# 强标记：句子命中任何一个，就说明它在讲招投标程序而不是投标内容
PROCEDURAL_MARKERS: tuple[tuple[str, str], ...] = (
    (r"\d{12,}", "保证金银行账号"),
    (r"投标保证金", "投标保证金"),
    (r"(?:一正二副|正本[一1]份|副本[二2]份|正本、副本|胶装|活页装订|信袋|封口处|密封袋)", "纸质标书装订/份数"),
    (r"U盘|u盘", "U盘电子版"),
    (r"网卡\s*MAC|MAC\s*地址|硬盘序列号|IP\s*地址", "防串标硬件信息"),
    (r"CA\s*数字证书|远程在线签到|远程解密|解密时长|解密失败|网上开标签到", "CA签到/解密"),
    (r"开标室|开标时启封|网上开标", "开标程序"),
    (r"采购预算上限|不得超过人民币?600万|预算金额", "采购预算"),
    (r"电子交易平台|金蝉电子招标|bid\s*格式", "交易平台操作"),
    # ── 评标相关：只剥离"组织程序"，**绝不剥离评标办法/评分标准/审查条款** ──
    # 旧规则是 (评标委员会|评委|评标办法|符合性审查|实质性响应审查) → 一律剥离，
    # 这条同时作用在两处，危害都很大：
    #   ① 生成前：技术章的【招标要求上下文】/【废标红线】里，评分标准与符合性
    #      审查条款被整句切掉 —— 章节看不到评分标准，就写不出对着标准应答的内容；
    #      符合性审查/实质性响应审查本身就是废标红线，切掉等于让某章漏项。
    #   ② 生成后（_repair_one 的整本修复）：命中句会被**从成稿里删掉**，
    #      于是"本技术方案响应评标办法中技术评分标准的要求"这种评委要找的
    #      应答句被静默删除 —— 既是丢正文，又正好删在最不该删的地方。
    # 真正的"程序性"只是评标的组织安排（纪律、时间地点、专家抽取与回避），
    # 这些与怎么写标书无关，剥离它们即可。
    (r"评标纪律|评标时间|评标地点|抽取(?:评标)?专家|专家回避|评标委员会(?:的)?组建",
     "评标组织程序"),
)

_SENT_SPLIT_RE = re.compile(r"(?<=[。；！？\n])")


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT_RE.split(text or "") if s]


def _is_table_line(ln: str) -> bool:
    return ln.lstrip().startswith("|")


def _strip_smart(text: str, judge) -> tuple[str, list[str]]:
    """按句剥离，但对 Markdown 表格整表判断。

    judge(sentence) -> 命中标签 or None

    为什么不能逐行删：第一版直接把命中的表格行删掉，结果一张商务偏离表
    只剩表头和零星几行 —— 表格被撕碎了，比不删更糟。所以表格要整表决策：
    命中行够多就整表拿掉，只命中一两行才逐行删（那样表格仍然完整）。
    """
    changes: list[str] = []
    if not text:
        return text, changes
    lines = text.split("\n")
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        if _is_table_line(lines[i]):
            j = i
            while j < len(lines) and _is_table_line(lines[j]):
                j += 1
            block = lines[i:j]
            data_rows = [r for r in block if not re.fullmatch(r"\s*\|[\s\-:|]+\|\s*", r)]
            bad = [(k, judge(r)) for k, r in enumerate(block) if judge(r)]
            if bad and len(bad) == len(data_rows):
                changes.append(f"{bad[0][1]}：整表 {len(data_rows)} 行全部命中，整表删除")
            elif bad:
                # 只删命中的行。删掉部分行不会破坏表格结构，比整表删掉更保险。
                keep = [r for k, r in enumerate(block) if not judge(r)]
                for k, lab in bad:
                    changes.append(f"{lab}：删除表格行 {block[k].strip()[:60]}")
                out_lines.extend(keep)
            else:
                out_lines.extend(block)
            i = j
            continue
        s = lines[i]
        if not s.strip():
            out_lines.append(s)
            i += 1
            continue
        if len(s) > 120:
            # 长段落按句剥离，保留段落结构（不能整段删，也不能拆成一行一句）
            kept: list[str] = []
            for sent in _split_sentences(s):
                lab = judge(sent)
                if lab and len(sent.strip()) > 6:
                    changes.append(f"{lab}：{sent.strip()[:60]}")
                else:
                    kept.append(sent)
            out_lines.append("".join(kept))
        else:
            lab = judge(s)
            if lab and len(s.strip()) > 6:
                changes.append(f"{lab}：{s.strip()[:60]}")
            else:
                out_lines.append(s)
        i += 1
    return "\n".join(out_lines), changes


def _proc_judge(s: str) -> str | None:
    if not s.strip():
        return None
    for pat, label in PROCEDURAL_MARKERS:
        if re.search(pat, s):
            return f"剥离程序性条款（{label}）"
    return None


def strip_procedural_clauses(text: str) -> tuple[str, list[str]]:
    """删掉招投标程序性句子/表格（用于非商务、资格作用域）。"""
    return _strip_smart(text, _proc_judge)


# ══════════════════════════════════════════════════════════════════════════
# 五之二、口径台账数字归一（全书唯一取值）
# ══════════════════════════════════════════════════════════════════════════
# 为什么需要：120 节真实生成实测里，**质保期又出现了 4 种取值**（13/48 节时只有 1 种）。
# 项目基本事实层与口径台账是"生成前约束"，模型在长书里仍会漂移；而设备参数早就有
# `enforce_device_params` 做事后强制统一，口径表覆盖的承诺数字却没有同类兜底 ——
# 这是唯一一项"规模越大越差"的指标。
#
# 设计原则（宁可漏改不可错改，这个函数会**直接改正文**）：
#   ① 只处理"单个数字+单位"能唯一确定的承诺项；报价/付款/验收**永不由程序改写**；
#   ② 标签与数字之间**不允许自由通配**，只允许几个连接词 —— 这样
#      "质保期结束后2年"天然不匹配（它不是主质保期，是另一个主语）；
#   ③ 单位与台账不一致时**跳过并留痕**，不做换算（口径表自己要求"不得换算"）；
#   ④ 主语漂移（易损件/备件的质保期）跳过，避免把合法分项承诺改错；
#   ⑤ 每一处改动都写进 changes，可审计、可回滚。
_LEDGER_NUMERIC_KEYS: dict[str, tuple[str, ...]] = {
    "warranty": ("质保期", "质量保证期", "质保期限"),
    "bid_validity": ("投标有效期", "投标文件有效期"),
    "response_time": ("响应时限", "故障响应时限"),
    "onsite_time": ("到场时限", "到达现场时限"),
}
# 明确排除：pricing / payment / acceptance —— 单值不唯一，且报价绝不允许程序改写。

_LEDGER_LINK = (r"(?:为|是|：|:|不少于|不低于|不短于|达到|共|计|"
                r"应不少于|应不低于|须不少于|不得少于)?\s*")
_LEDGER_NUM_UNITS = ("个月", "月", "年", "日历天", "天", "小时", "分钟")
_LEDGER_NUM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(" + "|".join(_LEDGER_NUM_UNITS) + r")"
)
# 主语漂移守卫：这些词出现在标签前 24 字内时，说明说的不是主承诺
_SUBJECT_SHIFT = {
    "warranty": ("易损件", "备件", "备品备件", "耗材", "随机附件", "胶管", "密封件"),
}


def _ledger_numeric_items(ledger: dict | None) -> list[tuple[str, str, str, str]]:
    """从台账里取出可归一的 (key, 标签, 数字, 单位)。

    台账 value 形如"自验收合格之日起24个月" —— 必须**只命中一个**数字+单位，
    否则说明这一项不是单值承诺，跳过（宁可漏改）。
    """
    out: list[tuple[str, str, str, str]] = []
    items = (ledger or {}).get("items") if isinstance(ledger, dict) else None
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        key = str(it.get("key") or "").strip()
        aliases = _LEDGER_NUMERIC_KEYS.get(key)
        if not aliases:
            continue
        value = str(it.get("value") or "")
        hits = _LEDGER_NUM_RE.findall(value)
        if len(hits) != 1:
            continue  # 0 个或 2 个以上数字：不是单值，交给人工
        num, unit = hits[0]
        for label in aliases:
            out.append((key, label, num, unit))
    return out


def _ledger_unit_compatible(
    num: str, unit: str, canon_num: str, canon_unit: str
) -> bool:
    """单位不同，但能**算术上精确**换算成台账单位时才允许改写。

    实测依据：用户那份真实交付稿里，同一个主质保期既写成"12个月"（76 次）
    又写成"质保期满1年"（24 次）—— 这是真正需要统一的全局不一致，
    而第一版"单位不同一律跳过"把它留了下来（0 处改动）。

    允许的只有两种：
      - 年 ↔ 月/个月：必须精确相等（1年=12个月 ✓，2年=24≠12 ✗ 不改）
      - 天 ↔ 日历天：同一个量的两种叫法，数字相等即改写
    其它一律返回 False（宁可漏改）。
    """
    if unit == canon_unit:
        return True
    _m = {"个月": 1, "月": 1, "年": 12}
    if unit in _m and canon_unit in _m:
        try:
            return float(num) * _m[unit] == float(canon_num) * _m[canon_unit]
        except ValueError:
            return False
    if {unit, canon_unit} <= {"天", "日历天"}:
        return num == canon_num
    return False


def enforce_ledger_commitments(
    text: str, ledger: dict | None
) -> tuple[str, list[str]]:
    """把正文里与台账冲突的承诺数字改回台账取值。"""
    changes: list[str] = []
    if not text:
        return text, changes
    targets = _ledger_numeric_items(ledger)
    if not targets:
        return text, changes

    for key, label, canon_num, canon_unit in targets:
        # 标签与数字之间**不允许自由通配**，但必须覆盖真实成稿里的写法。
        # 实测（用户那份真实交付稿 958 段扫描）：真实写法是
        #   "质保期自总公司整体验收合格之日起 12 个月"、"质保期满1年"
        # 而第一版只认"质保期为/：N"，于是**在真实文本上一次都没触发**（0 处改动）。
        # 现在允许两种真实句式，同时仍然排除"质保期结束后…"（自由通配已去掉）。
        pat = re.compile(
            r"(" + re.escape(label) + r")((?:自[^。；\n]{0,20}?起|为[^。；\n]{0,16}?起|"
            r"届满|满|为|是|：|:|"
            r"不少于|不低于|不短于|达到|共|计|应不少于|应不低于|须不少于|不得少于)?\s*)"
            r"(\d+(?:\.\d+)?)\s*(" + "|".join(_LEDGER_NUM_UNITS) + r")"
        )

        def _sub(m: re.Match) -> str:
            lab, link, num, unit = m.group(1), m.group(2), m.group(3), m.group(4)
            if num == canon_num and unit == canon_unit:
                return m.group(0)  # 已经一致
            guard = _SUBJECT_SHIFT.get(key)
            if guard:
                ctx = text[max(0, m.start() - 24):m.start()]
                hit = next((g for g in guard if g in ctx), "")
                if hit:
                    changes.append(
                        f"口径主语漂移，跳过（{lab} {num}{unit}，前文含{hit}）"
                    )
                    return m.group(0)
            if not _ledger_unit_compatible(num, unit, canon_num, canon_unit):
                changes.append(
                    f"口径单位不同，跳过不换算（{lab} {num}{unit} vs 台账 "
                    f"{canon_num}{canon_unit}）"
                )
                return m.group(0)
            changes.append(f"口径统一：{lab} {num}{unit} → {canon_num}{canon_unit}")
            return f"{lab}{link}{canon_num}{canon_unit}"

        text = pat.sub(_sub, text)

        # ── 检测但不改：不同主语的口径（结束后/届满后/满后…）──
        # 为什么要专门检测：这类句子在主模式里**根本不匹配**（连接词后必须紧跟数字），
        # 于是"质保期结束后2年"这种既不改也不报 —— 改是对的（它不是主质保期），
        # 但静默不说等于把问题藏起来。这里只做"看见并回报"，一个字符都不动。
        _diff_pat = re.compile(
            re.escape(label) + r"(?:结束后|届满后|满后|之后|以后|期满后|后)"
            r"[^。；\n]{0,12}?(\d+(?:\.\d+)?)\s*("
            + "|".join(_LEDGER_NUM_UNITS) + r")"
        )
        for _dm in _diff_pat.finditer(text):
            changes.append(
                f"口径不同主语，未自动统一（{label}…后 {_dm.group(1)}{_dm.group(2)}"
                f"，非台账项，保留原文）"
            )

    return text, changes


# ══════════════════════════════════════════════════════════════════════════
# 五、设备参数强制统一
# ══════════════════════════════════════════════════════════════════════════

# 参数名 → 允许出现的单位种类（用于判断是否同一个量）
PARAM_UNIT_KIND: dict[str, str] = {
    "整架初撑力": "force", "整架工作阻力": "force", "单柱初撑力": "force",
    "单柱工作阻力": "force",
    "支架高度": "len", "支架宽度": "len", "支架长度": "len", "移架步距": "len",
    "伸缩梁行程": "len", "侧推油缸行程": "len", "巷道高差": "len",
    "整组支架重量": "weight", "最大不可拆卸件重量": "weight",
    "最大运输外形尺寸": "size", "支护强度": "press", "底板比压": "press",
    "泵站压力": "press",
}
_UNIT_KIND = {
    "kN": "force", "KN": "force",
    "mm": "len", "MM": "len", "m": "len", "米": "len",
    "kg": "weight", "Kg": "weight", "KG": "weight", "吨": "weight", "t": "weight", "T": "weight",
    "MPa": "press", "Mpa": "press", "MPA": "press",
}

# 参数名在正文里的写法（要覆盖"初撑力""工作阻力"等简称）
_PARAM_ALIASES: dict[str, tuple[str, ...]] = {
    "整架初撑力": ("整架初撑力", "初撑力"),
    "整架工作阻力": ("整架工作阻力", "支架工作阻力", "额定工作阻力", "工作阻力"),
    "支架高度": ("支架高度", "支护高度", "高度适应范围", "支架高度适应范围"),
    "支架宽度": ("支架宽度",),
    "支架长度": ("支架长度",),
    "移架步距": ("移架步距", "步距"),
    "整组支架重量": ("整组支架重量", "支架重量", "整机重量"),
    "最大不可拆卸件重量": ("最大不可拆卸件重量", "不可拆卸件重量"),
    "最大运输外形尺寸": ("最大运输外形尺寸", "最大运输尺寸"),
    "支护强度": ("平均支护强度", "支护强度"),
    "底板比压": ("底板平均比压", "对底板比压", "底板比压"),
    # 泵站压力**故意不纳入强制统一**：招标文件里"（泵站压力40.6MPa）"是工作阻力
    # 那一行对应的压力注解，与"泵站压力31.5MPa"不是同一个量。强行统一会把
    # 正确的注解改成错的（实测 43 章被误改）。
}

# 所有参数写法合成一个正则，用于"同一子句里不许出现第二个参数名"的判定
_PARAM_RE_ENFORCE = re.compile(
    "|".join(re.escape(a) for al in _PARAM_ALIASES.values() for a in al)
)

# 区间感知的数值：`1700～3500`、`6*0.6*0.3`、`≤3.477`、`50±2%` 都要整段吃掉。
# 第一版只吃单个数字，"支架高度适应1700～3500mm"里的"3500mm"被单独替换，
# 结果变成"1700～1700～3500mm"。
_NP = r"[ΦφØ]?\d+(?:\.\d+)?"
_SEQ = (
    rf"[≤≥<>≈~～±]?\s*{_NP}"
    rf"(?:\s*[～~\-—至/、]\s*{_NP})*"
    rf"(?:\s*[*×x]\s*{_NP})*"
    rf"(?:\s*±\s*\d+(?:\.\d+)?\s*%|\s*%)?"
)
_NUM_FORCE = re.compile(rf"({_SEQ})\s*(kN|KN|千牛)(?![a-zA-Z])")
_NUM_LEN = re.compile(rf"({_SEQ})\s*(mm|MM|毫米|m|米)(?![a-zA-Z])")
_NUM_WEIGHT = re.compile(rf"({_SEQ})\s*(kg|Kg|KG|公斤|吨|t|T)(?![a-zA-Z])")
_NUM_PRESS = re.compile(rf"({_SEQ})\s*(MPa|Mpa|MPA|兆帕)(?![a-zA-Z])")
_NUM_SIZE = re.compile(rf"({_SEQ})\s*(mm|MM|毫米|m|米)(?![a-zA-Z])")

_NUM_RES = {
    "force": _NUM_FORCE, "len": _NUM_LEN, "weight": _NUM_WEIGHT,
    "press": _NUM_PRESS, "size": _NUM_SIZE,
}


def _to_kN(v: str) -> float | None:
    m = re.match(r"([\d.]+)", v.replace(",", ""))
    return float(m.group(1)) if m else None


# "1700mm至3500mm" 这种两侧都带单位的区间，数值正则吃不到后半段。
# 先归一成 "1700～3500mm"，区间才能被整段识别和替换。
_UNIT_ONLY = r"mm|MM|m|米|kN|吨|kg|t|MPa"
_RANGE_DUP_UNIT_RE = re.compile(
    rf"(\d+(?:\.\d+)?)\s*({_UNIT_ONLY})\s*至\s*(\d+(?:\.\d+)?)\s*(?:\2)?"
)


def normalize_ranges(text: str) -> str:
    return _RANGE_DUP_UNIT_RE.sub(lambda m: f"{m.group(1)}～{m.group(3)}{m.group(2)}", text or "")


# 编造型号：`DH(31.5)-835/160S` 这种在招标文件里一次都没出现过的型号。
# 招标文件没给型号时，投标人自己也没给，草稿里出现的一定是模型编的。
#
# 第一版把 `GB 3836.1-2021`、`MT 283-2014`、`ISO 14644-1`、`HRC52-58` 这些
# **国家标准号/材料硬度**也当成了编造型号，会把正确内容改成占位符。两条判据挡住：
#   ① 标准号前缀（GB/MT/AQ/ISO…）与材料硬度缩写（HRC/HB/HV…）一律跳过
#   ② 标准号写法里有空格（"GB 3836.1-2021"），产品型号连写（"DH(31.5)-835/160S"）
_MODEL_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z]{2,8})\s*[（(]?\s*[\d.]+\s*[)）]?\s*[-—]\s*\d+(?:/\d+)?[A-Za-z]{0,3}(?![A-Za-z0-9])"
)
# 无连字符的型号：ZY12000/28/63D、ZY8800/22/45 这种"字母+数字/数字/数字"写法
_MODEL_RE2 = re.compile(
    r"(?<![A-Za-z0-9])([A-Z]{2,8})\s*\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?){1,3}[A-Za-z]{0,3}(?![A-Za-z0-9])"
)
_PATENT_RE = re.compile(r"ZL\s*\d{4,}\s*\.?\s*[\dXx.]*")
_NOT_A_MODEL_PREFIX = frozenset((
    "GB", "GBT", "GBZ", "MT", "AQ", "ISO", "IEC", "EN", "JB", "DB", "HG", "SY",
    "YY", "QB", "TB", "CJ", "JG", "JT", "WS", "NY", "SN", "TSG", "DL", "SH",
    "FZ", "GA", "HJ", "JC", "LY", "QC", "SB", "SL", "WB", "YB", "ASTM", "DIN",
    "JIS", "HRC", "HRB", "HB", "HV", "HS", "HL", "MPa", "EMS", "OHS",
    # ER = 气体保护电弧焊用焊丝牌号（GB/T 8110 的 ER50-6、ER49-1 等）。
    # 实测事故：焊接工艺章节写"焊接材料（ER50-6）"，被本规则当成"设备型号
    # 招标文件未出现"替换成占位符，全库"焊丝"字样清零 —— ER50-6 是国标材料
    # 牌号而不是产品型号，属于误报。前缀跳过只会放过一个token，
    # 不会删掉正确内容，符合"宁可漏改不可错改"。
    "ER", "AWS", "E",
))


def strip_unknown_models(
    text: str, tender_text: str, allowed: set[str] | None = None
) -> tuple[str, list[str]]:
    """把招标文件里查不到的型号/专利号换成占位符。

    比对时**去掉全部标点**只留字母数字。原因：本规则第一版改掉了 3 处
    正确内容 —— 招标文件原文写的是 `DH(31.5)-835/160S`，某一章写成了全角
    括号的 `DH（31.5）-835/160S`，直接字符串比对查不到，就被判成"编造"。
    型号里真正有辨别力的是字母数字序列，半全角/连字符差异不该影响判断。
    """
    changes: list[str] = []
    if not text:
        return text, changes
    tnorm = re.sub(r"[^A-Za-z0-9]", "", tender_text or "")

    def check(rx: re.Pattern, label: str, model_guard: bool = False):
        nonlocal text

        def sub(m: re.Match) -> str:
            tok = m.group(0)
            if model_guard:
                if m.group(1) in _NOT_A_MODEL_PREFIX:
                    return tok
                if re.match(r"^[A-Z]{2,8}\s", tok):   # 有空格 → 标准号写法
                    return tok
            key = re.sub(r"[^A-Za-z0-9]", "", tok)
            if key and key in tnorm:
                return tok
            if allowed and key in allowed:
                return tok
            changes.append(f"{label} {tok.strip()} 招标文件未出现，判为编造 → 占位符")
            return PH % label

        text = rx.sub(sub, text)

    check(_PATENT_RE, "专利号")
    check(_MODEL_RE, "设备型号", model_guard=True)
    check(_MODEL_RE2, "设备型号", model_guard=True)
    return text, changes


def _locked_value(spec: dict, param: str, whole: bool) -> str:
    grp = spec.get("整架" if whole else "单柱") or {}
    return grp.get(param) or ""


@dataclass
class ParamFix:
    param: str
    device: str
    old: str
    new: str


def enforce_paired_values(
    text: str,
    specs: dict[str, dict],
    dev_re: "re.Pattern",
    alias2canon: dict[str, str],
    param_forms: list[tuple[str, str]],
) -> tuple[str, list[ParamFix]]:
    """处理"整架初撑力分别为8000kN与8000kN"这种并列句。

    为什么单设备扫描搞不定：这句话里一个设备名都没有，参数值有两个。
    `enforce_device_params` 只能沿用"上一个提到的设备"（超前），于是端头
    的 8000kN 被当成正确的放过去 —— 实测第 44 章因此同时写错端头的初撑力
    （8000 应为 10048）和整组重量（38吨 应为 50吨）。

    做法：在一个子句内，若参数后跟"分别"且恰好两个值，而该参数**之前**
    恰好提到两台设备，就按出现顺序一一对应强制统一。数量对不上就不动。
    """
    if not specs or not text or "分别" not in text:
        return text, []
    form2param = dict(param_forms)
    param_re = re.compile("|".join(re.escape(a) for a, _ in param_forms))
    fixes: list[ParamFix] = []

    # 逐子句处理：跨子句的"分别"没有意义，也会把别处的设备数进来
    parts = re.split(r"([。；\n])", text)
    for idx in range(0, len(parts), 2):
        seg = parts[idx]
        if "分别" not in seg:
            continue
        new_seg = seg
        # edits 必须**跨参数**累积后一次性回写：同一个子句里"整架初撑力"
        # 先被替换（8000kN → 10048kN，长度 +1）会改变后面"整组支架重量"
        # 的偏移，边算边改就改出"分别50吨吨与38吨"（覆盖了"为38"）。
        seg_edits: list[tuple[int, int, str]] = []
        for m in list(param_re.finditer(seg)):
            param = form2param.get(m.group(0))
            if not param:
                continue
            after = seg[m.end():]
            if "分别" not in after[:12]:
                continue
            kind = PARAM_UNIT_KIND.get(param)
            rx = _NUM_RES.get(kind or "")
            if not rx:
                continue
            # 取值窗口**必须**截到子句分隔符或下一个参数名：不截的话
            # "分别为8000kN与8000kN，整架工作阻力均为12500kN" 会抓出 3 个力值，
            # 数量对不上就整句放弃（这正是第 44 章没被修好的原因）。
            stop = re.search(r"[，,。；;：:\n]", after)
            window = after[:stop.start()] if stop else after
            nx = param_re.search(window, 1)
            if nx:
                window = window[:nx.start()]
            vals = list(rx.finditer(window))
            if len(vals) != 2:
                continue
            devs_before = [alias2canon[mm.group(0)] for mm in dev_re.finditer(seg[:m.start()])]
            # 去重保序（同一台设备可能被叫两次）
            seen, devs = set(), []
            for d in devs_before:
                if d not in seen:
                    seen.add(d)
                    devs.append(d)
            if len(devs) != 2:
                continue
            # 收集后统一从右往左应用：同一子句里"整架初撑力"先被替换会改变
            # 后面"整组支架重量"的偏移，边算边改会把"38吨"的位置算错，
            # 改出"分别50吨吨与38吨"这种残迹。
            for (dm, vm) in zip(devs, vals):
                spec = specs.get(dm)
                if not spec:
                    continue
                locked = _locked_value(spec, param, not param.startswith("单柱"))
                if not locked:
                    continue
                old_val = (vm.group(1) + vm.group(2)).strip()
                lk = locked.replace(" ", "")
                if old_val.replace(" ", "") == lk:
                    continue
                lu = re.search(r"[a-zA-Z\u4e00-\u9fa5%]+$", lk)
                ou = re.search(r"[a-zA-Z\u4e00-\u9fa5%]+$", old_val)
                if lu and ou and _UNIT_KIND.get(ou.group(0)) != _UNIT_KIND.get(lu.group(0)):
                    continue
                fixes.append(ParamFix(param, dm, old_val, lk))
                seg_edits.append((m.end() + vm.start(), m.end() + vm.end(), lk))
        for s, e, rep in sorted(seg_edits, reverse=True):
            new_seg = new_seg[:s] + rep + new_seg[e:]
        parts[idx] = new_seg
    return "".join(parts), fixes


def enforce_device_params(
    text: str,
    chapter_devices: list[str],
    specs: dict[str, dict],
) -> tuple[str, list[ParamFix]]:
    """把跑偏的设备参数改回招标文件锁定值。

    做法：从头扫描正文，遇到设备名就记住"当前在讲哪台设备"（段落级记忆），
    遇到参数名就取该设备的锁定值，若正文里的数值与之不符则替换。

    只在能明确判定设备归属时替换 —— 判不出设备就放过，宁可漏改不可错改。
    """
    if not specs or not text:
        return text, []

    text = normalize_ranges(text)

    dev_names: list[tuple[str, str]] = []  # (别名, 规范名)
    for dev, s in specs.items():
        for n in [dev] + list(s.get("aliases") or []):
            if n:
                dev_names.append((n, dev))
    dev_names.sort(key=lambda x: -len(x[0]))
    if not dev_names:
        return text, []

    dev_re = re.compile("|".join(re.escape(n) for n, _ in dev_names))
    alias2canon = dict(dev_names)

    param_forms: list[tuple[str, str]] = []  # (别名, 规范参数名)
    for p, al in _PARAM_ALIASES.items():
        for a in al:
            param_forms.append((a, p))
    param_forms.sort(key=lambda x: -len(x[0]))
    param_re = re.compile("|".join(re.escape(a) for a, _ in param_forms))
    form2param = dict(param_forms)

    # 先处理"分别为A与B"的并列句（它没有设备名前缀，单设备扫描认不出来），
    # 再走常规逐设备核对
    text, paired_fixes = enforce_paired_values(
        text, specs, dev_re, alias2canon, param_forms
    )

    fixes: list[ParamFix] = list(paired_fixes)

    # 设备名不再参与"消费式"扫描。原因：设备简称会吃掉参数名的开头 ——
    # 别名"端头支架"匹配到之后，剩下的"长度10m"里的"长度"已经不是参数名
    # （参数名是"支架长度"），于是"端头支架长度10m"永远核不上，实测第 44 章
    # 的支架长度错误一直改不掉。改成先给设备名建位置索引，再独立扫参数，
    # 两者允许重叠；参数的归属取"它前面最近一次出现的设备"。
    dev_hits = [(m.start(), m.end(), alias2canon[m.group(0)])
                for m in dev_re.finditer(text)]

    def _dev_at(pos: int) -> str | None:
        best = None
        for s, _e, canon in dev_hits:
            if s <= pos:
                best = canon
            else:
                break
        return best

    cur_dev: str | None = chapter_devices[0] if len(chapter_devices) == 1 else None
    edits: list[tuple[int, int, str]] = []
    for m in param_re.finditer(text):
        param = form2param.get(m.group(0))
        if not param:
            continue
        cur = _dev_at(m.start()) or cur_dev
        if not cur or cur not in specs:
            continue
        spec = specs[cur]
        # 单柱 vs 整架：**必须紧邻**（"立柱初撑力"/"单柱工作阻力"）才算单柱。
        # 第一版用 30 字窗口，"支架立柱初撑力检测（端尾支架初撑力不低于7758kN）"
        # 被判成单柱，7758kN 被错改成 1939kN —— 那个括号里明明写的是整架值。
        adj = text[max(0, m.start() - 6): m.start()]
        is_pillar = param.startswith("单柱") or bool(
            re.search(r"(?:立柱|单柱|每根|单根|每柱)的?$", adj)
        )
        # 放宽限定词识别：6 字窗口只认"紧邻末尾"，写"单柱设计工作阻力"
        # "立柱的额定工作阻力"时限定词不在末尾，会被判成整架，于是一个正确的
        # 单柱值被覆盖成整架值。再往前看一段，只要出现立柱/单柱类限定词、
        # 且这段里**没有**整架/整组/整机这类相反限定词，仍按单柱处理。
        if not is_pillar and param.startswith("整架"):
            wider = text[max(0, m.start() - 14): m.start()]
            if re.search(r"立柱|单柱|每根|单根|每柱|单架", wider) and not re.search(
                r"整架|整组|整机|全架", wider
            ):
                is_pillar = True
        if param.startswith("整架") and is_pillar:
            param = "单柱" + param[2:]
        if param.startswith("单柱") and not is_pillar:
            param = "整架" + param[2:]
        locked = _locked_value(spec, param, not param.startswith("单柱"))
        if not locked:
            continue
        kind = PARAM_UNIT_KIND.get(param)
        rx = _NUM_RES.get(kind or "")
        if not rx:
            continue
        # 数值只在同一个子句里找：遇到标点/另一个参数名/另一个设备名就停，
        # 否则会跨子句抓到别的设备的数值。
        raw_ahead = text[m.end(): m.end() + 40]
        cut = re.search(r"[。；，、（）()【】\n\|\"\u201c\u201d]", raw_ahead)
        look_ahead = raw_ahead[:cut.start()] if cut else raw_ahead
        if _PARAM_RE_ENFORCE.search(look_ahead) or dev_re.search(look_ahead):
            continue
        # "分别为A与B"的并列句已由 enforce_paired_values 按设备顺序处理过。
        # 这里若再按"上一个提到的设备"去核，会把刚改对的值又按错误的归属改回去
        # （实测"整组支架重量分别为50吨与38吨"被改回"38吨与38吨"）。
        if "分别" in look_ahead:
            continue
        vm = rx.search(look_ahead)
        if not vm:
            continue
        old_val = (vm.group(1) + vm.group(2)).strip()
        lk = locked.replace(" ", "")
        if old_val.replace(" ", "") == lk:
            continue
        # ── 防错改：正文数值恰好等于该设备的"单柱"真值时不覆盖 ──
        # 实测事故：招标文件的端头单柱工作阻力 683kN、超前单柱工作阻力 784kN
        # 在成稿里变成 0 次出现，而整架值 12500kN 出现 68 次。原因是模型写
        # "工作阻力683kN"时没带"单柱"限定词，本函数按整架处理，把正确的单柱值
        # 覆盖成了整架值。683/784 都是招标文件里真实存在的数，覆盖它属于
        # "错改"；按"宁可漏改不可错改"，这里跳过，只记日志留痕。
        if param.startswith("整架"):
            twin = _locked_value(spec, "单柱" + param[2:], False)
            if twin and _to_kN(old_val) is not None and _to_kN(old_val) == _to_kN(twin):
                logger.info(
                    "[一致性修复] 跳过覆盖 %s 的 %s：等于该设备单柱真值(%s)，"
                    "疑为立柱参数未写限定词，按不漏改原则保留",
                    cur, old_val, twin,
                )
                continue
        lu = re.search(r"[a-zA-Z\u4e00-\u9fa5%]+$", lk)
        ou = re.search(r"[a-zA-Z\u4e00-\u9fa5%]+$", old_val)
        if lu and ou and _UNIT_KIND.get(ou.group(0)) != _UNIT_KIND.get(lu.group(0)):
            continue
        start = m.end() + vm.start()
        end = m.end() + vm.end()
        if lu and ou and _to_kN(old_val) == _to_kN(locked):
            # 数值本来就对：只在单位写法确实不同时才动（8000kg → 8000Kg）。
            # "4850×1770×800mm" 与 "4850*1770*800mm" 数字单位都一样，不必改。
            if ou.group(0) == lu.group(0):
                continue
            fixes.append(ParamFix(param, cur, old_val, lk))
            edits.append((start, end, lk))
            continue
        # 区间重启清理：原文"支架高度适应1700mm至3500mm"替换后段会留下
        # "1700mm至"，先把它抹掉，得到"支架高度适应2500-4200mm"。
        prefix = text[max(0, m.start() - 2):start]
        m2 = re.search(r"(\d[\d.]*\s*(?:mm|MM|毫米|m|米|kN|吨|kg|t))\s*至\s*$", prefix)
        if m2:
            start = max(0, m.start() - 2) + m2.start()
        fixes.append(ParamFix(param, cur, old_val, lk))
        edits.append((start, end, lk))
    # 一次性从右往左回写，避免前面的替换改变后面记录的偏移
    out = text
    for s, e, rep in sorted(edits, reverse=True):
        out = out[:s] + rep + out[e:]
    return out, fixes


# ══════════════════════════════════════════════════════════════════════════
# 六、设备专属部件词（防止"破顶装置2.8t"抄到别的支架上）
# ══════════════════════════════════════════════════════════════════════════

# 只认"有名有姓的部件"。第一版用了宽泛的
# `[\u4e00-\u9fa5]{2,10}?(?:装置|千斤顶|...)`，结果把"通过销轴""高压胶管"
# "立柱和千斤顶"这种通用串当成某设备的专属部件，误删了 123 个句子。
_COMPONENT_RE = re.compile(
    r"[\u4e00-\u9fa5]{0,4}(?:破顶|护顶|底调|侧推|推移|伸缩|托梁|调架|防倒|抬底|护帮|"
    r"前梁|后梁|尾梁|导向|调角)[\u4e00-\u9fa5]{0,4}?"
    r"(?:装置|千斤顶|油缸|缸|梁|板|机构)"
)
_MIN_TERM_LEN = 4      # 太短的词（"销轴"）不具区分度
_MIN_TERM_HITS = 2     # 只提过一次的不算"该设备的标志性部件"

# 所有液压支架都有的通用件。**绝不能**当成某设备的专属部件，否则会把
# 正确内容删掉（实测"推移千斤顶""导向机构"被误判，误删了 47 个句子）。
# 判断上宁可漏（少删几个抄错的句子），也不能错（删掉正确内容）。
_GENERIC_COMPONENT_TERMS = {
    "推移千斤顶", "侧推千斤顶", "护顶千斤顶", "底调千斤顶", "调角千斤顶",
    "抬底千斤顶", "防倒千斤顶", "伸缩千斤顶", "前梁千斤顶", "尾梁千斤顶",
    "立柱", "千斤顶", "油缸", "伸缩梁", "托梁", "导向机构", "导向梁",
    "顶梁", "底座", "掩护梁", "前梁", "后梁", "尾梁", "护帮板", "调架机构",
}


def build_exclusive_terms(specs: dict[str, dict]) -> dict[str, set[str]]:
    """算出"只属于某一个设备"的部件词。

    破顶装置只在端尾支架的段落里出现 → 讲端头支架时提到它一定是抄错了。
    要求：词长 ≥4、在该设备段落里出现 ≥2 次、在其它设备段落里 0 次。

    注意必须先把段落里的空白合掉：招标文件表格把"推移 千斤 顶"拆成三行，
    不合空白的话 端头/超前 的"推移千斤顶"统计不到，会被误判成端尾专属，
    于是端头章节里所有讲推移千斤顶的句子都被删掉 —— 这是实测踩到的坑。
    """
    per_dev: dict[str, set[str]] = {}
    for dev, s in specs.items():
        txt = re.sub(r"\s+", "", s.get("section_text") or "")
        cnt: dict[str, int] = {}
        for m in _COMPONENT_RE.finditer(txt):
            t = m.group(0)
            if len(t) >= _MIN_TERM_LEN and t not in _GENERIC_COMPONENT_TERMS:
                cnt[t] = cnt.get(t, 0) + 1
        per_dev[dev] = {t for t, c in cnt.items() if c >= _MIN_TERM_HITS}
    excl: dict[str, set[str]] = {}
    for dev, terms in per_dev.items():
        others: set[str] = set()
        for d2, t2 in per_dev.items():
            if d2 != dev:
                others |= t2
        excl[dev] = {t for t in terms if t not in others and t not in _GENERIC_COMPONENT_TERMS}
    return excl


def strip_foreign_components(
    text: str,
    chapter_devices: list[str],
    specs: dict[str, dict],
    exclusive: dict[str, set[str]] | None = None,
    tender_text: str = "",
) -> tuple[str, list[str]]:
    """删掉"不属于当前所述设备"的部件描述。

    必须做**句级设备归属**：一章同时讲三台支架时，讲端尾的那句提到破顶装置
    是正确的，讲端头的那句提到才是抄错。只看"本章是否涉及端尾"会把正确的也删掉。
    做法与参数统一一致：从头扫描，遇到设备名就更新"当前设备"并向后沿用。
    """
    if not specs or not text:
        return text, []
    exclusive = exclusive if exclusive is not None else build_exclusive_terms(specs)
    owner: dict[str, str] = {}
    for d, terms in exclusive.items():
        for t in terms:
            owner[t] = d
    if not owner:
        return text, []

    dev_names: list[tuple[str, str]] = []
    for dev, s in specs.items():
        for n in [dev] + list(s.get("aliases") or []):
            if n:
                dev_names.append((n, dev))
    dev_names.sort(key=lambda x: -len(x[0]))
    dev_re = re.compile("|".join(re.escape(n) for n, _ in dev_names))
    alias2canon = dict(dev_names)

    state: dict[str, str | None] = {
        "dev": chapter_devices[0] if len(chapter_devices) == 1 else None
    }

    def judge(s: str) -> str | None:
        # 句内最后一次提到的设备决定这句话在讲谁
        last = None
        for m in dev_re.finditer(s):
            last = alias2canon.get(m.group(0))
        if last:
            state["dev"] = last
        cur = state["dev"]
        if not cur:
            return None
        bad = [t for t in owner if owner[t] != cur and t in s]
        if bad:
            return f"剥离他型设备专属部件（讲{cur}却提到{'、'.join(sorted(bad)[:3])}）"
        return None

    return _strip_smart(text, judge)


# ══════════════════════════════════════════════════════════════════════════
# 七、重复大表压缩
# ══════════════════════════════════════════════════════════════════════════

# 允许保留完整明细表的作用域
TABLE_ALLOWED_SCOPES = frozenset({SCOPE_SPARE, SCOPE_COMMERCIAL, SCOPE_TECHNICAL})

_SPARE_TABLE_KEYS = ("备件", "易损件", "随机附件", "专用工具", "外购件", "更换周期",
                     "定货号", "订货号", "厂家名称")
_TABLE_SUMMARY = (
    "随机标准附件、备品备件及专用工具严格按招标文件技术规格书明细足额配置，"
    "均为原厂全新正品，供货时随附煤安证书与合格证。完整明细见「备品备件及易损件」专章。"
)

# 含金额列的表**永远不压缩**。实测《投标总报价声明》里的 16 行"分项报价构成表"
# 只因为第 5 行写着"备品备件及易损件费用"，就被 looks_spare 判成备件表压成了一句
# 套话 —— 投标报价构成表被删是废标级事故，比表格重复严重得多。
_MONEY_COL_KEYS = ("报价", "单价", "合价", "金额", "总价", "费用", "税额", "价款", "价（", "价(")
# 备件明细表的结构特征：表头得同时有"名称"和"规格/型号/数量/单位"里的一个
_STRUCT_COL_KEYS = ("名称", "规格型号", "规格", "型号", "单位", "数量")


def _table_kind(body: str) -> str:
    """判断大表性质：money=含金额列（禁止压缩）；spare=像备件明细表；other=其它。"""
    rows = [ln.strip() for ln in (body or "").split("\n") if ln.lstrip().startswith("|")]
    if not rows:
        return "other"
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    flat = [c for r in cells for c in r]
    if sum(1 for c in flat if c and any(k in c for k in _MONEY_COL_KEYS)) >= 2:
        return "money"
    hdr = "".join(cells[0])
    if sum(1 for k in _STRUCT_COL_KEYS if k in hdr) >= 2:
        return "spare"
    return "other"


def _table_blocks(text: str) -> list[tuple[int, int]]:
    """返回连续表格行（含表头分隔行）的 [start, end) 偏移。"""
    lines = (text or "").split("\n")
    blocks: list[tuple[int, int]] = []
    offs: list[int] = []
    p = 0
    for ln in lines:
        offs.append(p)
        p += len(ln) + 1
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            if j - i >= 4:  # 至少 4 行才算"大表"
                blocks.append((offs[i], offs[j - 1] + len(lines[j - 1])))
            i = j
        else:
            i += 1
    return blocks


def _table_signature(body: str) -> frozenset[str]:
    """用**整行文字**（去掉数字与单位）做指纹，同一张表被粘贴十余遍 → 指纹相同。

    第一版用"各行的首格"，结果几乎所有表格首格都是"序号"或被规范化成空串，
    指纹全部撞车，误压了 163 张表。整行文字才真正有区分度。
    """
    rows: set[str] = set()
    for ln in (body or "").split("\n"):
        if not ln.lstrip().startswith("|"):
            continue
        txt = re.sub(r"[\s\d.,%≤≥<>～~±*×x/\\—\-]+", "", ln.strip().strip("|"))
        txt = re.sub(r"^[|:-]+", "", txt)
        if len(txt) >= 4:
            rows.add(txt)
    return frozenset(rows)


def dedupe_spare_tables(
    text: str, scope: str, keep: bool, seen_sigs: set[frozenset[str]] | None = None
) -> tuple[str, list[str], set[frozenset[str]]]:
    """压缩**重复**的备件/易损件明细大表。

    历史教训（三版都踩过坑）：
    ① 按作用域"只留第一张" → 连主要技术参数表也压掉；
    ② 用"表里出现过备件/专用工具字样"当判据 → 《投标总报价声明》的 16 行
       **分项报价构成表**只因为有一行"备品备件及易损件费用"就被压成一句套话，
       报价构成表被删是废标级事故；《与现有技术的对比优势》里的**综合对比汇总表**
       也因为一行"易损件更换周期"被压掉，而替换句讲的是备品备件，语义完全不符。
    ③ 所以现在同时要求两条：**结构上确实是备件明细表**（表头有"名称"+规格/数量类列）
       并且**指纹与前面某张表完全一致**。替换句 "见「备品备件及易损件」专章" 只对
       备件表成立，所以绝不能让其它类型的表走进来。
    含金额列的表一律不碰 —— 宁可书里多重复几张表，也不能少一张报价表。
    """
    seen_sigs = seen_sigs if seen_sigs is not None else set()
    if not text:
        return text, [], seen_sigs
    changes: list[str] = []
    out = text
    for start, end in reversed(_table_blocks(out)):
        body = out[start:end]
        if _table_kind(body) != "spare":
            continue
        sig = _table_signature(body)
        if not sig or len(sig) < 4:
            continue
        if sig in seen_sigs:
            rows = len([l for l in body.split("\n") if l.strip()])
            changes.append(f"压缩重复备件明细表（{rows} 行）→ 一句话概括")
            out = out[:start] + _TABLE_SUMMARY + out[end:]
        else:
            seen_sigs.add(sig)
    return out, changes, seen_sigs


# ══════════════════════════════════════════════════════════════════════════
# 八、编排
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ChapterRepair:
    title: str
    sort_order: int
    scope: str
    devices: list[str]
    content: str
    changes: list[str] = field(default_factory=list)
    # "看到了但故意没改"的口径冲突（单位不同 / 主语漂移）。
    # 与 changes 分开：changes 只统计**真的改了**的地方，
    # 而这里是要**回报给用户确认**的，不能让它在日志里静默消失。
    skipped: list[str] = field(default_factory=list)


@dataclass
class RepairReport:
    chapters: list[ChapterRepair]
    total_changes: int
    by_kind: dict[str, int]
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.total_changes:
            return "一致性修复：无需改动"
        parts = [f"{k}×{v}" for k, v in sorted(self.by_kind.items(), key=lambda x: -x[1])]
        return f"一致性修复：共 {self.total_changes} 处（{'、'.join(parts)}）"


def normalize_mixed_markdown(text: str) -> tuple[str, int]:
    """修掉"粗体标记包住标题标记"的混合写法：`**#### 地质条件匹配风险**`。

    导出器认 `#### 标题`（渲染成加粗正文）也认 `**标题**`，但不认两者嵌套，
    结果 `####` 四个井号原样漏进 Word —— 实测 10 段、40 个字面 `#`，
    正是"排版不规范"里最扎眼的一类。统一降级成加粗，语义不变、渲染正确。
    """
    if not text or ("#" not in text):
        return text, 0
    n = 0

    def _sub(m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"**{m.group(1).strip()}**"

    # **#### 标题** / **##### 标题**
    out = re.sub(r"\*\*\s*#{1,6}\s*([^*\n]+?)\s*\*\*", _sub, text)
    # #### **标题** / ## **标题**
    out = re.sub(r"^[ \t]*#{1,6}[ \t]*\*\*([^*\n]+?)\*\*[ \t]*$", _sub, out, flags=re.M)
    # 行内 `**# 标题**`
    out = re.sub(r"\*\*\s*#\s*([^*\n]+?)\s*\*\*", _sub, out)
    return out, n


def repair_chapter(
    title: str,
    content: str,
    sort_order: int,
    *,
    specs: dict[str, dict] | None = None,
    allowed: set[str] | None = None,
    exclusive: dict[str, set[str]] | None = None,
    seen_sigs: set[frozenset[str]] | None = None,
    spare_table_seen: bool = False,
    tender_text: str = "",
    ledger: dict | None = None,
    do_price: bool = True,
    do_params: bool = True,
    do_procedural: bool = True,
    do_tables: bool = True,
    do_ledger: bool = True,
) -> ChapterRepair:
    """对单章做确定性修复。"""
    text = content or ""
    text, c0 = normalize_mixed_markdown(text)
    scope = classify_scope(title, text)
    devs = detect_chapter_devices(title, text, specs or {})
    changes: list[str] = []
    skipped: list[str] = []
    if c0:
        changes.append(f"修正标题标记 ×{c0}")

    if do_price:
        text, c1 = canonicalize_placeholders(text)
        changes += ([f"占位符规范化 ×{c1}"] if c1 else [])
        text, c2 = strip_invented_prices(text, allowed)
        changes += c2
        text, c3 = strip_table_amounts(text, allowed)
        changes += c3
        if tender_text:
            text, c3b = strip_unknown_models(text, tender_text, allowed)
            changes += c3b

    if do_params and specs:
        text, fixes = enforce_device_params(text, devs, specs)
        changes += [f"参数统一：{f.device} 的 {f.param} {f.old} → {f.new}" for f in fixes]
        text, c4 = strip_foreign_components(text, devs, specs, exclusive, tender_text)
        changes += c4
        text, c4b = fix_derived_numbers(text)
        changes += c4b

    if do_procedural and scope not in PROCEDURAL_ALLOWED_SCOPES:
        text, c5 = strip_procedural_clauses(text)
        changes += c5

    # 口径台账数字归一：放在程序条款剥离之后、安全网之前 ——
    # 这样"归一"造成的任何过度改动都会被下面的 40% 安全网兜住。
    if do_ledger and ledger:
        text, c5b = enforce_ledger_commitments(text, ledger)
        for _c in c5b:
            # 跳过项单独收集：不冒充"改动"，但要回报
            if _c.startswith("口径单位不同") or _c.startswith("口径主语漂移") \
                    or _c.startswith("口径不同主语"):
                skipped.append(f"{title or ''}：{_c}")
            else:
                changes.append(_c)

    keep_table = scope in TABLE_ALLOWED_SCOPES and not spare_table_seen
    if do_tables:
        text, c6, _ = dedupe_spare_tables(text, scope, keep_table, seen_sigs)
        changes += c6

    # ── 修复幅度安全网 ──
    # 修复只应"改正"，不该"删内容"。历史上 spare table 压缩规则一次性毁掉 85 处
    # （含 16 行的分项报价构成表），也是静默的。这里统一兜底：一轮修复砍掉原文
    # 40% 以上，判定为规则误伤，整章回退原文（宁可漏改不可错改，丢正文是废标级）。
    if len(content or "") >= 100 and len(text) < len(content) * 0.60:
        # 注意：只保留"回退"这一条记录 —— 被丢弃的那些改动不能再进报告，
        # 否则 ChangesReport 会把没发生的改动统计进去（虚增改动数）。
        return ChapterRepair(
            title or "", sort_order, scope, devs, content or "",
            [f"修复删减 {len(content)}->{len(text)} 字超过 40%，判定误伤，"
             f"整章回退原文（已丢弃 {len(changes)} 处改动）"],
            skipped,
        )

    # 收尾：清理连续空行
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return ChapterRepair(title or "", sort_order, scope, devs, text, changes, skipped)


def repair_bid(
    chapters: list[dict],
    *,
    specs: dict[str, dict] | None = None,
    ledger: dict | None = None,
    tender_text: str = "",
    dry_run: bool = False,
) -> RepairReport:
    """整本修复。chapters: [{"title","content","sort_order"}]，按顺序处理。"""
    specs = specs or {}
    allowed = allowed_amounts(ledger)
    exclusive = build_exclusive_terms(specs) if specs else None
    out: list[ChapterRepair] = []
    by_kind: dict[str, int] = {}
    spare_seen = False
    seen_sigs: set[frozenset[str]] = set()
    for ch in chapters:
        r = repair_chapter(
            ch.get("title") or "", ch.get("content") or "",
            int(ch.get("sort_order") or 0),
            specs=specs, allowed=allowed, exclusive=exclusive,
            seen_sigs=seen_sigs, spare_table_seen=spare_seen,
            tender_text=tender_text, ledger=ledger,
        )
        if r.scope in TABLE_ALLOWED_SCOPES and any(
            k in (r.content or "") for k in _SPARE_TABLE_KEYS
        ):
            spare_seen = True
        for c in r.changes:
            key = c.split("（")[0].split("：")[0].split(" ×")[0]
            by_kind[key] = by_kind.get(key, 0) + 1
        out.append(r)
    total = sum(len(r.changes) for r in out)
    report = RepairReport(out, total, by_kind)
    # 口径冲突里"看到了但故意没改"的，汇总回报给用户确认 ——
    # 静默留着等于把问题藏起来，自动改掉又可能改错（宁漏不错）。
    _skipped_left = [s for r in out for s in r.skipped]
    if _skipped_left:
        # 按**类别**去重计数：同一句话在一章里出现 8 次是 1 类问题不是 8 个，
        # 否则回报给用户的信息会被重复项淹没。
        _uniq = Counter(s.split("：", 1)[1] if "：" in s else s
                        for s in _skipped_left)
        _items = "；".join(f"{k}（{v} 处）" for k, v in _uniq.most_common(6))
        report.notes.append(
            f"口径未自动统一 {len(_skipped_left)} 处、共 {len(_uniq)} 类"
            f"（单位不同或主语不同，按「宁可漏改不可错改」保留原文，请人工确认）："
            + _items + ("…" if len(_uniq) > 6 else "")
        )
    if not specs:
        report.notes.append("未取到设备技术规格（招标文件无标准技术规格书结构），已跳过参数统一")
    logger.info("[一致性修复] %s", report.summary())
    return report