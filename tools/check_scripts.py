# -*- coding: utf-8 -*-
"""Windows 脚本守卫：检查 .ps1 / .bat 的编码与行尾。

为什么需要它：
  * Windows PowerShell 5.1 读 **无 BOM** 的 UTF-8 .ps1 时会按 ANSI(GBK) 解码，
    中文立即变乱码，甚至撑破 here-string 导致 "Unexpected token" 语法错误
    （本项目实测：install.ps1 掉 BOM 后整份脚本无法解析）。
  * cmd.exe 读 **LF** 行尾的 .bat 会逐行报"不是内部或外部命令"。

用法：
    python tools/check_scripts.py            # 检查仓库根目录下的 .ps1 / .bat
    python tools/check_scripts.py --root .   # 指定目录
退出码：全部正常为 0，否则为 1。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BOM = b"\xef\xbb\xbf"


def line_endings(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    crlf = lf = 0
    for i, byte in enumerate(data):
        if byte == 0x0A:
            if i and data[i - 1] == 0x0D:
                crlf += 1
            else:
                lf += 1
    return crlf, lf


def check_ps1(path: Path) -> list[str]:
    problems = []
    data = path.read_bytes()
    if not data.startswith(BOM):
        problems.append("缺 UTF-8 BOM（PowerShell 5.1 会把中文读成乱码，可能直接语法报错）")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        problems.append("不是合法 UTF-8：%s" % exc)
        return problems
    if text.count("{") != text.count("}"):
        problems.append("花括号数量不匹配（{ %d 个 / } %d 个）" % (text.count("{"), text.count("}")))
    return problems


def check_bat(path: Path) -> list[str]:
    problems = []
    crlf, lf = line_endings(path)
    if lf:
        problems.append("存在 %d 处纯 LF 行尾（cmd.exe 逐行报错），需要转成 CRLF" % lf)
    if not crlf:
        problems.append("没有任何 CRLF 行尾，文件可能不是 Windows 行尾")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="检查 .ps1 / .bat 的编码与行尾")
    ap.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    targets = sorted(list(root.glob("*.ps1")) + list(root.glob("*.bat")))
    if not targets:
        print("未找到 .ps1 / .bat，跳过")
        return 0

    bad = 0
    print("检查目录：%s" % root)
    for path in targets:
        problems = check_ps1(path) if path.suffix == ".ps1" else check_bat(path)
        crlf, lf = line_endings(path)
        head = "BOM %s" % ("有" if path.read_bytes().startswith(BOM) else "无")
        if problems:
            bad += 1
            print("  [X] %-16s CRLF=%-4d LF=%-4d %s" % (path.name, crlf, lf, head))
            for p in problems:
                print("        - %s" % p)
        else:
            print("  [OK] %-16s CRLF=%-4d LF=%-4d %s" % (path.name, crlf, lf, head))

    print()
    if bad:
        print("结论：%d 个文件需要修复（.ps1 补 UTF-8 BOM；.bat 转 CRLF）" % bad)
        return 1
    print("结论：全部正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())