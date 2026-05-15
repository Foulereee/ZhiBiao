from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from core.llm_gateway.gateway import LLMGateway


@dataclass
class SkillContext:
    project_id: UUID | str
    db: AsyncSession | None
    llm: LLMGateway
    parameters: dict = field(default_factory=dict)
    knowledge_base: Any = None
    progress_callback: callable | None = None


@dataclass
class SkillResult:
    success: bool
    data: dict = field(default_factory=dict)
    tokens_consumed: int = 0
    sources: list[dict] = field(default_factory=list)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


class Skill(ABC):
    name: str = ""
    description: str = ""
    category: str = ""
    version: str = "1.0.0"
    triggers: list[str] = []

    @abstractmethod
    async def execute(self, ctx: SkillContext) -> SkillResult: ...

    async def safe_execute(self, ctx: SkillContext) -> SkillResult:
        try:
            if ctx.progress_callback:
                await ctx.progress_callback(self.name, "started", {})
            result = await self.execute(ctx)
            if ctx.progress_callback:
                await ctx.progress_callback(self.name, "completed", result.data)
            return result
        except Exception as e:
            if ctx.progress_callback:
                await ctx.progress_callback(self.name, "failed", {"error": str(e)})
            return SkillResult(success=False, error=f"{str(e)}\n{traceback.format_exc()}")
