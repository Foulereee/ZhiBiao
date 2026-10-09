"""Word 导出字体统一工具(问题由实测导出文件 XML 定位)。

实测证据:
  * 生成端只用 python-docx 的 ``run.font.name = "宋体"``,只会写出
    ``<w:rFonts w:ascii="宋体" w:hAnsi="宋体"/>``,不会写 ``w:eastAsia``。
    Word 对**中文字符**取 ``w:eastAsia``,缺失时回退到 docDefaults 里的
    ``w:eastAsiaTheme="minorEastAsia"``(等线/Calibri),而数字与英文仍按
    ``w:ascii`` 用宋体 —— 同一行出现两种字体,即"导出 Word 字体不统一"。
    (实测 /tmp/1.bin: 260/260 个 run 都是这种缺 eastAsia 的写法。)
  * 排版链路 DocxFormatSkill 把正文设成 仿宋_GB2312,个别 run 残留 宋体,
    于是 apply_format=true / false 两条导出链路给出的字体互不相同。
  * 容器里既没有宋体也没有黑体(fc-match 宋体 → DejaVuSans),PDF 同样受影响。

本模块对**打包好的 .docx** 做一次归一化,同时修 document.xml / header*.xml /
footer*.xml / styles.xml:
  1. 按原有中文意图补齐 ``w:eastAsia``(黑体族→标题字体,其余→正文字体);
  2. 中文族字体收敛为"正文一种 / 标题一种",消除 仿宋_GB2312 与 宋体 混用;
  3. 西文统一 Times New Roman(整段本就是黑体的标题保持黑体);
  4. 清除 asciiTheme / hAnsiTheme / eastAsiaTheme / cstheme —— 它们会覆盖显式字体;
  5. 同步改写 docDefaults 与 Normal 样式,让未显式设字体的 run 也一致。

归一化失败不会影响导出:调用方拿到空列表就按原文件继续下发。
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


BODY_CN = "宋体"
HEADING_CN = "黑体"
WESTERN = "Times New Roman"

# 标题族中文字体(含常见别名)
_HEADING_FONTS = (
    "黑体", "simhei", "微软雅黑", "microsoft yahei", "方正小标宋", "小标宋",
    "思源黑体", "noto sans cjk", "微软雅黑 light", "等线 light", "heiti",
)
# 正文族中文字体(含常见别名)
_BODY_FONTS = (
    "宋体", "simsun", "新宋体", "nsimsun", "仿宋", "fangsong", "仿宋_gb2312",
    "楷体", "kaiti", "楷体_gb2312", "等线", "dengxian", "华文中宋",
    "思源宋体", "noto serif cjk", "book antiqua", "幼圆",
)

_THEME_ATTRS = ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme")

# 形如 Heading1 / 标题1 / 1 / h1 / Title 的段落样式视作标题。
# 注意：这里只认 1-9 单个数字 —— WPS/HIK 导出的正文样式 styleId 是 "11"/"25" 这类
# 两位数，旧的 [1-9]\d? 会把它们当标题，把正文字体一并改成黑体。
_HEADING_STYLE_RE = re.compile(r"(?i)^(heading\s*\d*|[1-9]|标题\s*\d*|title|h[1-9])$")
# 同上,但必须能取出级别数字
_HEADING_LEVEL_RE = re.compile(r"(?i)^(?:heading\s*|标题\s*|h)?([1-9])$")

_XML_PART_RE = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")


def _lower(name: str | None) -> str:
    return (name or "").strip().lower().replace(" ", "")


def _is_heading_font(name: str | None) -> bool:
    n = _lower(name)
    return bool(n) and any(h.replace(" ", "") in n for h in _HEADING_FONTS)


def _is_cjk_font(name: str | None) -> bool:
    n = _lower(name)
    if not n:
        return False
    return any(b.replace(" ", "") in n for b in _BODY_FONTS) or _is_heading_font(name)


def _canonicalize(
    rfonts,
    heading: bool,
    body_cn: str,
    heading_cn: str,
    western: str,
    *,
    force_heading: bool = False,
) -> None:
    """就地修正一个 w:rFonts:补 eastAsia、收敛中文字体、统一西文、去主题引用。

    ``force_heading`` 用于语义明确的标题(如 pStyle=Heading1):此时一律用标题字体,
    连排版链路误套上来的正文字体也纠正掉。
    """
    cur_ea = rfonts.get(_q("eastAsia"))
    cur_ascii = rfonts.get(_q("ascii")) or rfonts.get(_q("hAnsi")) or ""

    if force_heading:
        cn = heading_cn
    elif cur_ea:
        cn = heading_cn if _is_heading_font(cur_ea) else body_cn
    elif heading:
        # 段落已判定为标题(如整段加粗+大字号):标题统一黑体
        cn = heading_cn
    elif _is_cjk_font(cur_ascii):
        # 原代码把中文字体写在 ascii 上(如 ascii="宋体"),按它的意图判定
        cn = heading_cn if _is_heading_font(cur_ascii) else body_cn
    else:
        cn = body_cn

    # 标题(含其中的西文/数字)整体统一黑体,正文西文统一 Times New Roman ——
    # 这样"未排版"与"排版"两条导出链路给出的字体完全一致
    west = heading_cn if cn == heading_cn else western

    rfonts.set(_q("ascii"), west)
    rfonts.set(_q("hAnsi"), west)
    rfonts.set(_q("eastAsia"), cn)
    rfonts.set(_q("cs"), west)
    for attr in _THEME_ATTRS:
        if rfonts.get(_q(attr)) is not None:
            del rfonts.attrib[_q(attr)]


def _run_sz(run) -> int:
    rpr = run.find(_q("rPr"))
    if rpr is None:
        return 0
    sz = rpr.find(_q("sz"))
    if sz is None:
        return 0
    try:
        return int(sz.get(_q("val")) or 0)
    except (TypeError, ValueError):
        return 0


def _run_bold(run) -> bool:
    rpr = run.find(_q("rPr"))
    if rpr is None:
        return False
    b = rpr.find(_q("b"))
    if b is None:
        return False
    return (b.get(_q("val")) or "1").strip() not in ("0", "false")


def _has_text(run) -> bool:
    return any((t.text or "").strip() for t in run.iter(_q("t")))


def _heading_level(p):
    """语义标题级别(1-9);非语义标题返回 None(pStyle=Heading1/标题1/1,或 outlineLvl)。"""
    ppr = p.find(_q("pPr"))
    if ppr is None:
        return None
    st = ppr.find(_q("pStyle"))
    if st is not None:
        v = (st.get(_q("val")) or "").strip()
        m = _HEADING_LEVEL_RE.match(v)
        if m:
            return int(m.group(1))
        if v.lower().startswith("heading") or v in ("Title", "标题"):
            return 1
    ol = ppr.find(_q("outlineLvl"))
    if ol is not None:
        try:
            return int(ol.get(_q("val")) or "") + 1
        except (TypeError, ValueError):
            return None
    return None


def _visual_heading(p) -> bool:
    """整段加粗且字号 >= 14pt(28 半点)视为标题,例如封面大标题。"""
    runs = [r for r in p.findall(_q("r")) if _has_text(r)]
    if not runs:
        return False
    return all(_run_bold(r) for r in runs) and max(_run_sz(r) for r in runs) >= 28


def _fix_document(xml_bytes: bytes, body_cn: str, heading_cn: str, western: str) -> bytes:
    root = etree.fromstring(xml_bytes)
    for p in root.iter(_q("p")):
        lvl = _heading_level(p)
        # 一~三级标题语义明确,字体一律黑体 —— 排版链路把正文字体套到标题上时也纠正
        force = lvl is not None and lvl <= 3
        heading = bool(lvl is not None or _visual_heading(p))
        for rfonts in p.iter(_q("rFonts")):
            _canonicalize(rfonts, heading, body_cn, heading_cn, western, force_heading=force)
    # 段落样式/字符样式引用处可能也带 rFonts(幂等,重复处理安全)
    for rfonts in root.iter(_q("rFonts")):
        _canonicalize(rfonts, False, body_cn, heading_cn, western)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _fix_styles(xml_bytes: bytes, body_cn: str, heading_cn: str, western: str) -> bytes:
    root = etree.fromstring(xml_bytes)
    # 1) 各命名样式
    for style in root.iter(_q("style")):
        sid = (style.get(_q("styleId")) or "").strip()
        name_el = style.find(_q("name"))
        sname = (name_el.get(_q("val")) if name_el is not None else "") or ""
        heading = bool(_HEADING_STYLE_RE.match(sid) or _HEADING_STYLE_RE.match(sname.strip()))
        for rfonts in style.iter(_q("rFonts")):
            _canonicalize(rfonts, heading, body_cn, heading_cn, western)
    # 2) 全局默认(docDefaults) —— 这是中文字符回退主题字体的根源
    dd = root.find(_q("docDefaults"))
    if dd is not None:
        rprd = dd.find(_q("rPrDefault"))
        if rprd is None:
            rprd = etree.SubElement(dd, _q("rPrDefault"))
        rpr = rprd.find(_q("rPr"))
        if rpr is None:
            rpr = etree.SubElement(rprd, _q("rPr"))
        rfonts = rpr.find(_q("rFonts"))
        if rfonts is None:
            rfonts = etree.Element(_q("rFonts"))
            rpr.insert(0, rfonts)
        rfonts.set(_q("ascii"), western)
        rfonts.set(_q("hAnsi"), western)
        rfonts.set(_q("eastAsia"), body_cn)
        rfonts.set(_q("cs"), western)
        for attr in _THEME_ATTRS:
            if rfonts.get(_q(attr)) is not None:
                del rfonts.attrib[_q(attr)]
    # 3) Normal 样式
    for style in root.iter(_q("style")):
        if (style.get(_q("styleId")) or "") == "Normal":
            rpr = style.find(_q("rPr"))
            if rpr is None:
                rpr = etree.SubElement(style, _q("rPr"))
            rfonts = rpr.find(_q("rFonts"))
            if rfonts is None:
                rfonts = etree.Element(_q("rFonts"))
                rpr.insert(0, rfonts)
            _canonicalize(rfonts, False, body_cn, heading_cn, western)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def normalize_docx_fonts(
    docx_path: str | Path,
    *,
    body_cn: str = BODY_CN,
    heading_cn: str = HEADING_CN,
    western: str = WESTERN,
) -> list[str]:
    """把已生成的 .docx 字体归一化(原地改写)。

    返回被改写的部件名列表;失败返回空列表(调用方按原文件继续下发)。
    """
    path = Path(docx_path)
    if not path.exists():
        return []
    try:
        with zipfile.ZipFile(path) as zin:
            items = [(info, zin.read(info.filename)) for info in zin.infolist()]
        out: list[tuple[zipfile.ZipInfo, bytes]] = []
        changed: list[str] = []
        for info, data in items:
            name = info.filename
            try:
                if name == "word/styles.xml":
                    data = _fix_styles(data, body_cn, heading_cn, western)
                    changed.append(name)
                elif _XML_PART_RE.match(name):
                    data = _fix_document(data, body_cn, heading_cn, western)
                    changed.append(name)
            except etree.XMLSyntaxError:
                pass  # 该部件解析失败就原样保留
            out.append((info, data))
        if not changed:
            return []
        tmp = path.with_name(path.stem + ".normalized.docx")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info, data in out:
                info.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(info, data)
        shutil.move(str(tmp), str(path))
        return changed
    except Exception:  # noqa: BLE001 - 归一化失败不得影响导出
        try:
            path.with_name(path.stem + ".normalized.docx").unlink(missing_ok=True)
        except OSError:
            pass
        return []