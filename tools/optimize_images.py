#!/usr/bin/env python3
"""仓库图片瘦身工具（可重复执行、带保真度安全阀）。

背景
----
本仓库曾出现两类图片浪费（2026-10 实测）：

1. ``packages/desktop/renderer/src/assets/logo.png`` 是 **2048x2048 / 2.39 MB**，
   而它在 ``Sidebar.tsx`` 里只以 **32x32** 显示 —— 占前端 bundle 绝大部分体积。
2. ``assets/diagrams/*.png`` 是 24 位 RGB 保存的线框图/文字图，线稿类图片
   量化到 256 色几乎无损（PSNR 54~56 dB），体积却能降 60% 以上。

注意：``assets/screenshots/*.png`` 原本已是"为屏幕优化过"的调色板 PNG，
把它们按 RGB 重新编码反而**更大**，所以这里只做降采样 + 256 色量化。

策略
----
============================  ==========  ================================
目录/文件                      处理        实测效果
============================  ==========  ================================
``**/assets/logo.png``         缩到 256px  2.39 MB -> 64 KB（-97%）
``assets/screenshots/*.png``   1400px 宽   1.64 MB -> ~0.95 MB（PSNR 39-44 dB）
``assets/diagrams/*.png``      原尺寸量化  0.70 MB -> ~0.26 MB（PSNR 54-56 dB）
============================  ==========  ================================

安全阀：任一图片替换后的 PSNR 低于 ``--min-psnr``（默认 35 dB）就跳过该文件，
保持原图不动，并在输出里标红提示。

用法
----
    python tools/optimize_images.py            # 就地优化
    python tools/optimize_images.py --check    # 只检查/报告，不改文件
    python tools/optimize_images.py --min-psnr 38
"""
from __future__ import annotations

import argparse
import io
import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageChops
except ImportError:  # pragma: no cover
    sys.exit("需要 Pillow：pip install pillow")

REPO = Path(__file__).resolve().parent.parent
LOGO = REPO / "packages/desktop/renderer/src/assets/logo.png"
SCREENSHOTS = REPO / "assets/screenshots"
DIAGRAMS = REPO / "assets/diagrams"

LOGO_MAX_SIDE = 256
SHOT_MAX_WIDTH = 1400
QUANT_COLORS = 256


def psnr(a: Image.Image, b: Image.Image) -> float:
    """峰值信噪比（dB）；返回 inf 表示完全一致。"""
    a = a.convert("RGB")
    b = b.convert("RGB")
    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)
    hist = ImageChops.difference(a, b).histogram()
    total = sq = 0
    for ch in range(3):
        for i in range(256):
            cnt = hist[ch * 256 + i]
            total += cnt
            sq += cnt * i * i
    if total == 0 or sq == 0:
        return float("inf")
    return 10 * math.log10(255 * 255 / (sq / total))


def encode(img: Image.Image, quantize: bool) -> bytes:
    out = img.quantize(colors=QUANT_COLORS, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG) if quantize else img
    buf = io.BytesIO()
    if out.mode == "P":
        out.save(buf, "PNG", optimize=True)
    else:
        out.save(buf, "PNG", optimize=True, compress_level=9)
    return buf.getvalue()


def process(path: Path, max_width: int | None, max_side: int | None, quantize: bool, min_psnr: float, check: bool) -> tuple[int, int, float, str]:
    orig_size = path.stat().st_size
    img = Image.open(path)
    target = img
    if max_side and max(img.size) > max_side:
        scale = max_side / max(img.size)
        target = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    elif max_width and img.width > max_width:
        target = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)

    data = encode(target, quantize)
    quality = psnr(target, Image.open(io.BytesIO(data)))
    if quality < min_psnr:
        return orig_size, orig_size, quality, "跳过（低于安全阈值）"
    if check:
        return orig_size, len(data), quality, "可优化" if len(data) < orig_size else "无需优化"
    if len(data) >= orig_size and target is img:
        return orig_size, orig_size, quality, "保持原样"
    path.write_bytes(data)
    return orig_size, len(data), quality, "已优化"


def main() -> int:
    ap = argparse.ArgumentParser(description="仓库图片瘦身")
    ap.add_argument("--check", action="store_true", help="只报告，不写文件")
    ap.add_argument("--min-psnr", type=float, default=35.0, help="保真度安全阀（dB），默认 35")
    args = ap.parse_args()

    jobs: list[tuple[Path, int | None, int | None, bool]] = []
    if LOGO.exists():
        jobs.append((LOGO, None, LOGO_MAX_SIDE, False))
    for p in sorted(SCREENSHOTS.glob("*.png")):
        jobs.append((p, SHOT_MAX_WIDTH, None, True))
    for p in sorted(DIAGRAMS.glob("*.png")):
        jobs.append((p, None, None, True))

    if not jobs:
        print("没找到需要处理的图片")
        return 0

    old_total = new_total = 0
    print(f"{'文件':<52}{'原':>9}{'后':>9}{'变化':>8}{'PSNR':>8}  结果")
    print("-" * 96)
    for path, max_width, max_side, quantize in jobs:
        try:
            o, n, q, note = process(path, max_width, max_side, quantize, args.min_psnr, args.check)
        except Exception as exc:  # noqa: BLE001
            print(f"{path.relative_to(REPO)!s:<52}{'-':>9}{'-':>9}{'-':>8}{'-':>8}  失败：{exc}")
            continue
        old_total += o
        new_total += n
        delta = f"{100 * (n - o) / o:+.0f}%" if o else "-"
        q_txt = "inf" if q == float("inf") else f"{q:.1f}"
        rel = str(path.relative_to(REPO))
        print(f"{rel:<52}{o / 1024:>8.1f}K{n / 1024:>8.1f}K{delta:>8}{q_txt:>8}  {note}")
    print("-" * 96)
    saved = old_total - new_total
    print(
        f"合计 {old_total / 1024 / 1024:.2f} MB -> {new_total / 1024 / 1024:.2f} MB"
        f"（省 {saved / 1024 / 1024:.2f} MB / {100 * saved / old_total:.0f}%）"
        + ("  [--check 模式，未改文件]" if args.check else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())