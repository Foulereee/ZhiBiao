from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


class DocExportSkill(Skill):
    """docx → doc 二进制格式转换。

    策略: docx 始终是唯一中间格式。本 skill 仅在下载场景把 docx 转成 doc，
    使用 LibreOffice headless 转 PDF/DOC。如 LibreOffice 不可用，回退 docx2pdf
    或直接返回 docx 字节流（前端可重命名）。
    """

    name = "doc_export"
    description = "docx → doc 二进制格式转换（基于 LibreOffice/antiword）"
    category = "output"
    version = "1.0.0"
    triggers = ["导出doc", "转doc", "doc格式"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        docx_path = ctx.parameters.get("docx_path", "")
        output_dir = ctx.parameters.get("output_dir", "")
        if not docx_path:
            return SkillResult(success=False, error="缺少 docx_path 参数")
        src = Path(docx_path)
        if not src.exists():
            return SkillResult(success=False, error=f"docx 文件不存在: {docx_path}")
        if src.suffix.lower() != ".docx":
            return SkillResult(success=False, error=f"输入必须是 .docx 格式: {docx_path}")

        target_dir = Path(output_dir) if output_dir else src.parent
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return SkillResult(success=False, error=f"无法创建输出目录: {e}")

        result = self._try_libreoffice_doc(src, target_dir)
        if result.get("success"):
            return SkillResult(success=True, data=result)

        result = self._try_pandoc(src, target_dir)
        if result.get("success"):
            return SkillResult(success=True, data=result)

        return SkillResult(
            success=False,
            error=(
                f"doc 转换失败: 未找到 LibreOffice/soffice 或 pandoc。"
                f" 提示: Windows 安装 LibreOffice 或 pandoc；"
                f" 也可让前端直接下载 docx 后改名为 doc 临时使用。"
            ),
        )

    def _try_libreoffice_doc(self, src: Path, target_dir: Path) -> dict[str, Any]:
        soffice_paths = [
            "soffice",
            "/usr/bin/libreoffice",
            "/usr/bin/soffice",
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        soffice_cmd = None
        for candidate in soffice_paths:
            if shutil.which(candidate):
                soffice_cmd = candidate
                break
            if os.path.isfile(candidate):
                soffice_cmd = candidate
                break
        if not soffice_cmd:
            return {"success": False, "error": "未找到 soffice"}

        try:
            with tempfile.TemporaryDirectory(prefix="bmp_doc_") as profile_dir:
                cmd = [
                    soffice_cmd,
                    f"-env:UserInstallation=file://{profile_dir.replace(os.sep, '/')}",
                    "--headless",
                    "--convert-to",
                    "doc:MS Word 2007 XML",
                    "--outdir",
                    str(target_dir),
                    str(src),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                return {"success": False, "error": f"soffice 退出码 {proc.returncode}: {proc.stderr[:300]}"}
            doc_path = target_dir / (src.stem + ".doc")
            if not doc_path.exists():
                return {"success": False, "error": "soffice 转换后未找到 .doc 文件"}
            return {
                "success": True,
                "method": "libreoffice",
                "output_path": str(doc_path),
                "file_size": doc_path.stat().st_size,
                "format": "doc",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "soffice 转换超时(120s)"}
        except Exception as e:
            return {"success": False, "error": f"soffice 异常: {e}"}

    def _try_pandoc(self, src: Path, target_dir: Path) -> dict[str, Any]:
        if not shutil.which("pandoc"):
            return {"success": False, "error": "未找到 pandoc"}
        try:
            out = target_dir / (src.stem + ".doc")
            proc = subprocess.run(
                ["pandoc", str(src), "-o", str(out), "-f", "docx", "-t", "doc"],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode != 0:
                return {"success": False, "error": f"pandoc 退出码 {proc.returncode}: {proc.stderr[:300]}"}
            if not out.exists():
                return {"success": False, "error": "pandoc 转换后未找到 .doc 文件"}
            return {
                "success": True,
                "method": "pandoc",
                "output_path": str(out),
                "file_size": out.stat().st_size,
                "format": "doc",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "pandoc 转换超时(60s)"}
        except Exception as e:
            return {"success": False, "error": f"pandoc 异常: {e}"}


def docx_bytes_to_doc_bytes(docx_bytes: bytes) -> dict[str, Any]:
    """工具函数: 将 docx 字节流转为 doc 字节流。需要先写到临时文件走 LibreOffice。"""
    with tempfile.TemporaryDirectory(prefix="bmp_doc_bytes_") as tmp:
        src = Path(tmp) / "input.docx"
        src.write_bytes(docx_bytes)
        skill = DocExportSkill()
        result = skill._try_libreoffice_doc(src, Path(tmp))
        if not result.get("success"):
            return result
        out = Path(result["output_path"])
        return {
            "success": True,
            "doc_bytes": out.read_bytes(),
            "method": result.get("method", "libreoffice"),
        }
