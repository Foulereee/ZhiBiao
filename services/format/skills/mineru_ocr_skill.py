from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from core.skill_engine.base import Skill, SkillContext, SkillResult
from core.ocr import get_mineru_client, MinerUError

logger = logging.getLogger(__name__)


class MinerUOcrSkill(Skill):
    name = "mineru_ocr"
    description = "调用 MinerU OCR 从 PDF/图片/扫描件中抽取文字与版面（云端或自部署）"
    category = "input"
    version = "1.0.0"
    triggers = ["MinerU", "OCR抽取", "扫描件识别", "PDF抽文字"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_path = ctx.parameters.get("file_path", "")
        mode_override = ctx.parameters.get("mode")
        api_key_override = ctx.parameters.get("api_key")
        endpoint_override = ctx.parameters.get("endpoint")
        timeout_override = ctx.parameters.get("timeout")
        options = ctx.parameters.get("options") or {}

        if not file_path:
            return SkillResult(success=False, error="缺少 file_path 参数")
        if not Path(file_path).exists():
            return SkillResult(success=False, error=f"文件不存在: {file_path}")

        try:
            client = get_mineru_client(
                mode=mode_override,
                api_key=api_key_override,
                endpoint=endpoint_override,
                timeout=int(timeout_override) if timeout_override else None,
            )
        except MinerUError as e:
            return SkillResult(success=False, error=f"MinerU 客户端初始化失败: {e}")

        async def _progress(name: str, payload: dict) -> None:
            if ctx.progress_callback:
                try:
                    await ctx.progress_callback(name, payload)
                except Exception:
                    pass

        try:
            result = await client.extract(file_path, on_progress=_progress)
        except MinerUError as e:
            return SkillResult(success=False, error=str(e))
        except asyncio.TimeoutError:
            return SkillResult(success=False, error="MinerU 抽取超时")
        except Exception as e:
            logger.exception("MinerU 抽取异常")
            return SkillResult(success=False, error=f"MinerU 抽取失败: {e}")

        markdown = result.get("markdown") or ""
        return SkillResult(
            success=True,
            data={
                "markdown": markdown,
                "length": len(markdown),
                "images": result.get("images") or {},
                "meta": result.get("meta") or {},
                "source": result.get("source", "mineru"),
                "mode": client.mode,
            },
        )
