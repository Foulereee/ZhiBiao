from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.settings import get_settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# 降低 SQLAlchemy 引擎日志级别（太多 INFO 日志）
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
from core.exceptions import (
    LLMGatewayError,
    JsonRepairError,
    SkillNotFoundError,
    UnsupportedFormatError,
    GateNotPassedException,
    ProjectNotFoundError,
)
from services.database import init_db, close_db, is_db_ready
from services.routers import projects, interpret, generate, check, format_doc, skills, llm_config, news, knowledge, rbac, ai_image, auth, agent_runtime, mineru_config, api_key, app_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from services.skill_bootstrap import register_builtin_skills
    from core.task_manager import TaskManager
    from services.database import async_session
    register_builtin_skills()
    await init_db()

    # 同步预置数据源 (YAML -> DB),仅做幂等写入,不抛错
    try:
        from services.news.source_registry import sync_sources_to_db
        async with async_session()() as _sdb:
            synced = await sync_sources_to_db(_sdb)
            await _sdb.commit()
            if synced:
                logging.getLogger("news").info(f"已同步 {synced} 个新数据源到注册表")
    except Exception as _e:
        logging.getLogger("news").warning(f"同步数据源失败 (可忽略): {_e}")

    # Periodic TaskManager cleanup
    async def _periodic_cleanup():
        tm = TaskManager.instance()
        while True:
            await asyncio.sleep(tm._cleanup_interval)
            tm.cleanup_old_tasks()

    cleanup_task = asyncio.create_task(_periodic_cleanup())

    # 平台设置里的 LLM 配置要真正生效:启动时读一次,之后周期刷新。
    # (get_llm_gateway() 每次比对配置签名,签名变了自动重建网关。)
    from services.llm_factory import llm_config_refresher, refresh_llm_config
    try:
        await refresh_llm_config()
    except Exception as _e:
        logging.getLogger("llm").warning(f"启动时读取 LLM 配置失败 (可忽略): {_e}")
    llm_config_task = asyncio.create_task(llm_config_refresher())

    yield
    cleanup_task.cancel()
    llm_config_task.cancel()
    for _t in (cleanup_task, llm_config_task):
        try:
            await _t
        except asyncio.CancelledError:
            pass
    await close_db()


_boot_settings = get_settings()
app = FastAPI(
    # 品牌信息统一来自 .env 的 BMP_APP_NAME / BMP_APP_TAGLINE / BMP_APP_VERSION。
    # 注意：FastAPI 的 title/version 在启动时固定，改完 .env 后 OpenAPI 文档标题
    # 要重建容器才会变；而 /api/app-config/config、健康检查、前端界面都是
    # 实时读取的，改完刷新页面即可。
    title=f"{_boot_settings.app_name} API",
    description=_boot_settings.app_tagline,
    version=_boot_settings.app_version,
    lifespan=lifespan,
)

import os

_electron_origins = [
    "http://localhost:15168",     # Vite dev (项目定制端口)
    "http://127.0.0.1:15168",
    "http://localhost:5173",      # Vite dev (默认端口，兼容)
    "http://127.0.0.1:5173",
    "http://localhost:4173",      # Vite preview
    "http://127.0.0.1:4173",
    "app://.",                    # Electron file protocol
    "file://",
]
_extra_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
if _extra_origins:
    _electron_origins.extend([o.strip() for o in _extra_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_electron_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "User-Agent", "X-Requested-With", "X-API-Key"],
    max_age=600,
)


@app.exception_handler(LLMGatewayError)
async def llm_gateway_error_handler(request: Request, exc: LLMGatewayError):
    return JSONResponse(status_code=502, content={"detail": f"LLM网关错误: {str(exc)}"})


@app.exception_handler(JsonRepairError)
async def json_repair_error_handler(request: Request, exc: JsonRepairError):
    return JSONResponse(status_code=422, content={"detail": f"JSON修复失败: {str(exc)}"})


@app.exception_handler(SkillNotFoundError)
async def skill_not_found_handler(request: Request, exc: SkillNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(UnsupportedFormatError)
async def unsupported_format_handler(request: Request, exc: UnsupportedFormatError):
    return JSONResponse(status_code=415, content={"detail": str(exc)})


@app.exception_handler(GateNotPassedException)
async def gate_not_passed_handler(request: Request, exc: GateNotPassedException):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(ProjectNotFoundError)
async def project_not_found_handler(request: Request, exc: ProjectNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误",
            "error": str(exc),
            "traceback": tb if get_settings().debug else None,
        },
    )


app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(projects.router, prefix="/api/projects", tags=["项目管理"])
app.include_router(interpret.router, prefix="/api/interpret", tags=["招标解读"])
app.include_router(generate.router, prefix="/api/generate", tags=["投标生成"])
app.include_router(check.router, prefix="/api/check", tags=["投标检查"])
app.include_router(format_doc.router, prefix="/api/format", tags=["文档输出"])
app.include_router(skills.router, prefix="/api/skills", tags=["Skill管理"])
app.include_router(llm_config.router, prefix="/api/llm", tags=["LLM配置"])
app.include_router(news.router, prefix="/api/news", tags=["资讯中心"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["知识库"])
app.include_router(rbac.router, prefix="/api/rbac", tags=["权限管理"])
app.include_router(ai_image.router, prefix="/api/ai-image", tags=["AI配图"])
app.include_router(agent_runtime.router, prefix="/api/agent", tags=["多Agent编排"])
# 兼容历史路径：router 自带 prefix="/agent"，上面的注册产生 /api/agent/agent/run 等
# 重复前缀路径（保留，不能删）。这里额外再注册一次同一 router，使干净路径也可用：
# /api/agent/run、/api/agent/run_step、/api/agent/status/{project_id}、/api/agent/resume/{project_id}
# 依赖（require_any_auth）与 tags 均随 router 本身保持不变。
app.include_router(agent_runtime.router, prefix="/api", tags=["多Agent编排"])
app.include_router(mineru_config.router, prefix="/api/mineru", tags=["MinerU OCR"])
app.include_router(api_key.router, prefix="/api/api-keys", tags=["API Key 管理"])
app.include_router(app_config.router, prefix="/api/app-config", tags=["品牌配置"])


@app.get("/api/health")
async def health_check():
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "tagline": settings.app_tagline,
        "version": settings.app_version,
        "db_ready": is_db_ready(),
    }


@app.get("/api/stats")
async def get_stats():
    from core.skill_engine.registry import SkillRegistry
    from services.llm_factory import get_llm_gateway
    registry = SkillRegistry.instance()
    try:
        gateway = get_llm_gateway()
        token_usage = gateway.get_token_summary()
    except Exception:
        token_usage = {}
    return {
        "skills_count": len(registry._skills),
        "skills": registry.list_all(),
        "token_usage": token_usage,
        "db_ready": is_db_ready(),
    }
