from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None

if FastMCP is not None:
    mcp = FastMCP("BidMaster Pro MCP Server")
else:
    class _MCPStub:
        def tool(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
        def resource(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
        def run(self, *args, **kwargs):
            logger.warning("MCP server not available: 'mcp' package not installed. Install with: pip install mcp")
    mcp = _MCPStub()


@mcp.tool()
async def interpret_tender(project_id: str) -> str:
    from services.database import async_session
    from services.routers.interpret import interpret_tender as _interpret
    async with async_session() as db:
        result = await _interpret(project_id, db)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def generate_outline(project_id: str, mode: str = "aligned") -> str:
    from services.database import async_session
    from services.routers.generate import generate_outline as _gen_outline
    async with async_session() as db:
        result = await _gen_outline(project_id, mode, db)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def run_compliance_check(project_id: str) -> str:
    from services.database import async_session
    from services.routers.check import check_compliance as _check
    async with async_session() as db:
        result = await _check(project_id, db)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def run_full_check(project_id: str) -> str:
    from services.database import async_session
    from services.routers.check import full_check as _full
    async with async_session() as db:
        result = await _full(project_id, db)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def run_selfcheck(project_id: str) -> str:
    from services.database import async_session
    from services.routers.check import run_selfcheck as _selfcheck
    async with async_session() as db:
        result = await _selfcheck(project_id, db)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def search_knowledge(kb_id: str, query: str, top_k: int = 5) -> str:
    from services.database import async_session
    from services.routers.knowledge import search_knowledge_base as _search
    async with async_session() as db:
        result = await _search(kb_id, query, top_k, db)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def list_skills() -> str:
    from core.skill_engine.registry import SkillRegistry
    registry = SkillRegistry.instance()
    return json.dumps({"skills": registry.list_all()}, ensure_ascii=False)


@mcp.tool()
async def get_project_status(project_id: str) -> str:
    from services.database import async_session
    from services.routers.projects import get_project as _get
    async with async_session() as db:
        result = await _get(project_id, db)
    return json.dumps(result, ensure_ascii=False)


@mcp.resource("bidmaster://skills")
def get_skills_resource() -> str:
    from core.skill_engine.registry import SkillRegistry
    registry = SkillRegistry.instance()
    return json.dumps(registry.list_all(), ensure_ascii=False)


@mcp.resource("bidmaster://project/{project_id}")
def get_project_resource(project_id: str) -> str:
    import asyncio
    from services.database import async_session
    from services.routers.projects import get_project as _get

    async def _fetch():
        async with async_session() as db:
            return await _get(project_id, db)

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_fetch())
        return json.dumps(result, ensure_ascii=False)
    finally:
        loop.close()


if __name__ == "__main__":
    mcp.run()
