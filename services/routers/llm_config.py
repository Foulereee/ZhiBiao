from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import AgentConfig, LLMProviderConfig
from services.llm_factory import get_llm_gateway
from services.middleware.rbac_middleware import get_current_user, require_permission
from services.models import User

router = APIRouter(dependencies=[Depends(get_current_user)])


class AgentModelConfig(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    enabled: bool = True


DEFAULT_AGENTS = [
    {
        "name": "interpret",
        "display_name": "招标解读Agent",
        "description": "解读招标文件，提取关键信息、评分标准、资质要求",
        "model": "",
        "temperature": 0.3,
        "max_tokens": 8192,
        "enabled": True,
    },
    {
        "name": "outline",
        "display_name": "大纲生成Agent",
        "description": "根据解读结果生成投标大纲，对齐评分项",
        "model": "",
        "temperature": 0.5,
        "max_tokens": 4096,
        "enabled": True,
    },
    {
        "name": "content",
        "display_name": "内容生成Agent",
        "description": "根据大纲逐章节生成标书内容",
        "model": "",
        "temperature": 0.7,
        "max_tokens": 8192,
        "enabled": True,
    },
    {
        "name": "check",
        "display_name": "质量检查Agent",
        "description": "对生成内容进行合规性、一致性、完整性检查",
        "model": "",
        "temperature": 0.2,
        "max_tokens": 4096,
        "enabled": True,
    },
    {
        "name": "format",
        "display_name": "格式排版Agent",
        "description": "对文档进行格式排版和美化",
        "model": "",
        "temperature": 0.1,
        "max_tokens": 2048,
        "enabled": True,
    },
    {
        "name": "final_check",
        "display_name": "终审Agent",
        "description": "最终全面检查，确保无遗漏",
        "model": "",
        "temperature": 0.1,
        "max_tokens": 4096,
        "enabled": True,
    },
    {
        "name": "export",
        "display_name": "导出Agent",
        "description": "导出最终投标文件",
        "model": "",
        "temperature": 0.0,
        "max_tokens": 2048,
        "enabled": True,
    },
]


@router.get("/agent-models")
async def list_agent_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentConfig).order_by(AgentConfig.name))
    db_agents = result.scalars().all()

    db_map = {a.name: a for a in db_agents}

    agents = []
    for default in DEFAULT_AGENTS:
        agent_name = default["name"]
        if agent_name in db_map:
            cfg = db_map[agent_name].config or {}
            agents.append({
                "name": agent_name,
                "display_name": cfg.get("display_name", default["display_name"]),
                "description": cfg.get("description", default["description"]),
                "model": cfg.get("model", ""),
                "temperature": cfg.get("temperature", default["temperature"]),
                "max_tokens": cfg.get("max_tokens", default["max_tokens"]),
                "enabled": db_map[agent_name].enabled,
            })
        else:
            agents.append(default)

    return {"agents": agents}


@router.put("/agent-models/{agent_name}")
async def update_agent_model(
    agent_name: str,
    config: AgentModelConfig,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.name == agent_name)
    )
    agent = result.scalar_one_or_none()

    config_dict = {
        "display_name": config.display_name,
        "description": config.description,
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }

    if agent:
        agent.config = config_dict
        agent.enabled = config.enabled
    else:
        agent = AgentConfig(
            name=agent_name,
            workflow_dsl={},
            skills=[],
            config=config_dict,
            enabled=config.enabled,
        )
        db.add(agent)

    await db.flush()

    return {"success": True, "name": agent_name}


@router.post("/agent-models/reset")
async def reset_agent_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentConfig))
    agents = result.scalars().all()
    for agent in agents:
        agent.config = {}
        agent.enabled = True
    await db.flush()

    return {"success": True, "message": "已重置所有Agent模型配置为默认值"}


@router.get("/providers")
async def list_providers():
    return {"providers": [
        {"id": "deepseek", "name": "DeepSeek", "models": ["deepseek-chat", "deepseek-reasoner"]},
        {"id": "zhipu", "name": "智谱AI", "models": ["glm-4-plus", "glm-4-flash"]},
        {"id": "qianfan", "name": "百度千帆", "models": ["ernie-4.0", "ernie-3.5"]},
        {"id": "dashscope", "name": "阿里百炼", "models": ["qwen-max", "qwen-plus", "qwen-turbo"]},
        {"id": "siliconflow", "name": "硅基流动", "models": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen2.5-72B-Instruct", "Qwen/Qwen2.5-32B-Instruct", "THUDM/glm-4-9b-chat"]},
        {"id": "ollama", "name": "Ollama(本地)", "models": ["qwen2.5", "llama3.1", "mistral"]},
        {"id": "openai", "name": "OpenAI", "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]},
    ]}


@router.post("/test")
async def test_connection(config: dict):
    try:
        from core.llm_gateway import LLMGateway
        model = config.get("model", "deepseek/deepseek-chat")
        gateway = LLMGateway({
            "providers": [{"api_key": config.get("api_key", ""), "api_base": config.get("api_base", "")}],
            "default_model": model,
            "fallback_models": [],
            "max_retries": 1,
        })
        result = await gateway.chat(
            messages=[{"role": "user", "content": "你好，请回复'连接成功'"}],
            temperature=0.1,
        )
        return {"success": True, "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/usage")
async def get_token_usage():
    gateway = get_llm_gateway()
    return gateway.get_token_summary()


@router.get("/default-model")
async def get_default_model(db: AsyncSession = Depends(get_db)):
    """读取已保存的默认 LLM 配置：优先数据库表 llm_provider_configs（is_default=True），其次环境变量。"""
    import os

    result = await db.execute(
        select(LLMProviderConfig).where(LLMProviderConfig.is_default == True, LLMProviderConfig.enabled == True)
    )
    db_default = result.scalar_one_or_none()

    if db_default:
        model = db_default.default_model or f"{db_default.provider_id}/default"
        api_key_masked = ""
        if db_default.api_key:
            if len(db_default.api_key) <= 8:
                api_key_masked = "*" * len(db_default.api_key)
            else:
                api_key_masked = db_default.api_key[:3] + "*" * (len(db_default.api_key) - 6) + db_default.api_key[-3:]
        provider_id = db_default.provider_id
        model_name = db_default.default_model or ""
        if "/" in model_name:
            provider_id, model_name = model_name.split("/", 1)
        return {
            "success": True,
            "configured": True,
            "model": model,
            "provider_id": provider_id,
            "model_name": model_name,
            "api_base": db_default.api_base or "",
            "api_key": api_key_masked,
            "has_api_key": bool(db_default.api_key),
            "source": "db",
            "config_id": db_default.id,
            "display_name": db_default.display_name or "",
        }

    env_model = (
        os.environ.get("BMP_LLM_DEFAULT_MODEL")
        or os.environ.get("LLM_DEFAULT_MODEL")
        or os.environ.get("DEFAULT_MODEL")
        or ""
    ).strip()
    env_api_key = (
        os.environ.get("BMP_LLM_API_KEY")
        or os.environ.get("LLM_API_KEY")
        or os.environ.get("API_KEY")
        or ""
    ).strip()
    env_api_base = (
        os.environ.get("BMP_LLM_API_BASE")
        or os.environ.get("LLM_API_BASE")
        or os.environ.get("API_BASE")
        or os.environ.get("OPENAI_API_BASE")
        or ""
    ).strip()

    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"
    )
    try:
        env_real = os.path.realpath(env_path)
        project_root = os.path.realpath(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        )
        if (
            os.path.exists(env_path)
            and (env_real.startswith(project_root + os.sep) or env_real == project_root)
        ):
            with open(env_path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == "BMP_LLM_DEFAULT_MODEL" and v and not env_model:
                        env_model = v
                    elif k == "BMP_LLM_API_KEY" and v and not env_api_key:
                        env_api_key = v
                    elif k == "BMP_LLM_API_BASE" and v and not env_api_base:
                        env_api_base = v
    except Exception as e:
        logger.warning(f"[llm/default-model] 读取 .env 失败: {e}")

    provider_id = ""
    model_name = env_model
    if "/" in env_model:
        provider_id, model_name = env_model.split("/", 1)
    else:
        provider_id = "custom"

    api_key_masked = ""
    if env_api_key:
        if len(env_api_key) <= 8:
            api_key_masked = "*" * len(env_api_key)
        else:
            api_key_masked = env_api_key[:3] + "*" * (len(env_api_key) - 6) + env_api_key[-3:]

    return {
        "success": True,
        "configured": bool(env_model),
        "model": env_model,
        "provider_id": provider_id,
        "model_name": model_name,
        "api_base": env_api_base,
        "api_key": api_key_masked,
        "has_api_key": bool(env_api_key),
        "source": "env",
    }


def _mask_key(k: str) -> str:
    if not k:
        return ""
    if len(k) <= 8:
        return "*" * len(k)
    return k[:3] + "*" * (len(k) - 6) + k[-3:]


@router.get("/configs")
async def list_llm_configs(db: AsyncSession = Depends(get_db)):
    """列出所有 LLM 供应商配置（API Key 始终脱敏）。"""
    result = await db.execute(
        select(LLMProviderConfig).order_by(LLMProviderConfig.is_default.desc(), LLMProviderConfig.created_at)
    )
    rows = result.scalars().all()
    return {
        "success": True,
        "configs": [
            {
                "id": r.id,
                "provider_id": r.provider_id,
                "display_name": r.display_name or "",
                "api_key_masked": _mask_key(r.api_key),
                "has_api_key": bool(r.api_key),
                "api_base": r.api_base or "",
                "default_model": r.default_model or "",
                "is_default": bool(r.is_default),
                "enabled": bool(r.enabled),
                "note": r.note or "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
    }


@router.get("/configs/{config_id}/reveal")
async def reveal_config_key(config_id: str, db: AsyncSession = Depends(get_db)):
    """获取单条配置的真实 API Key（需要已登录且有权限）。"""
    result = await db.execute(select(LLMProviderConfig).where(LLMProviderConfig.id == config_id))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    return {"success": True, "api_key": cfg.api_key}


class LLMConfigCreate(BaseModel):
    provider_id: str
    display_name: str | None = None
    api_key: str
    api_base: str | None = None
    default_model: str | None = None
    enabled: bool = True
    note: str | None = None


@router.post("/configs")
async def create_llm_config(payload: LLMConfigCreate, db: AsyncSession = Depends(get_db)):
    import re
    if not re.match(r"^[A-Za-z0-9._\-]{1,64}$", payload.provider_id):
        raise HTTPException(status_code=400, detail="供应商 ID 格式不合法")
    if not payload.api_key or len(payload.api_key) < 4:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    if payload.api_base and not re.match(r"^https?://", payload.api_base):
        raise HTTPException(status_code=400, detail="API Base 须以 http:// 或 https:// 开头")

    cfg = LLMProviderConfig(
        provider_id=payload.provider_id,
        display_name=payload.display_name,
        api_key=payload.api_key,
        api_base=payload.api_base,
        default_model=payload.default_model,
        enabled=payload.enabled,
        note=payload.note,
    )
    if cfg.enabled and not (await _any_default_exists(db)):
        cfg.is_default = True
    db.add(cfg)
    await db.flush()
    return {"success": True, "id": cfg.id}


class LLMConfigUpdate(BaseModel):
    display_name: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    default_model: str | None = None
    enabled: bool | None = None
    note: str | None = None


@router.put("/configs/{config_id}")
async def update_llm_config(config_id: str, payload: LLMConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LLMProviderConfig).where(LLMProviderConfig.id == config_id))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    if payload.api_key is not None:
        if len(payload.api_key) < 4:
            raise HTTPException(status_code=400, detail="API Key 长度不合法")
        cfg.api_key = payload.api_key
    if payload.api_base is not None:
        cfg.api_base = payload.api_base
    if payload.display_name is not None:
        cfg.display_name = payload.display_name
    if payload.default_model is not None:
        cfg.default_model = payload.default_model
    if payload.enabled is not None:
        cfg.enabled = payload.enabled
    if payload.note is not None:
        cfg.note = payload.note
    await db.flush()
    return {"success": True}


@router.delete("/configs/{config_id}")
async def delete_llm_config(config_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LLMProviderConfig).where(LLMProviderConfig.id == config_id))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    was_default = bool(cfg.is_default)
    await db.delete(cfg)
    await db.flush()
    if was_default:
        new_first = await db.execute(select(LLMProviderConfig).order_by(LLMProviderConfig.created_at).limit(1))
        first = new_first.scalar_one_or_none()
        if first:
            first.is_default = True
            await db.flush()
    return {"success": True}


@router.post("/configs/{config_id}/default")
async def set_default_config(config_id: str, db: AsyncSession = Depends(get_db)):
    await _clear_defaults(db)
    result = await db.execute(select(LLMProviderConfig).where(LLMProviderConfig.id == config_id))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    cfg.is_default = True
    await db.flush()
    return {"success": True}


async def _clear_defaults(db: AsyncSession):
    all_defaults = await db.execute(select(LLMProviderConfig).where(LLMProviderConfig.is_default == True))
    for row in all_defaults.scalars().all():
        row.is_default = False
    await db.flush()


async def _any_default_exists(db: AsyncSession) -> bool:
    r = await db.execute(select(LLMProviderConfig).where(LLMProviderConfig.is_default == True))
    return r.scalar_one_or_none() is not None


@router.put("/default-model")
async def set_default_model(config: dict, db: AsyncSession = Depends(get_db)):
    model = str(config.get("model", "")).strip()
    api_key = str(config.get("api_key", "")).strip()
    api_base = str(config.get("api_base", "")).strip()

    if not model:
        return {"success": False, "error": "模型不能为空"}

    import re
    if not re.match(r"^[A-Za-z0-9._/\-:]{1,128}$", model):
        return {"success": False, "error": "模型名称包含非法字符"}

    if api_key and not re.match(r"^[A-Za-z0-9._\-]{8,256}$", api_key):
        return {"success": False, "error": "API Key 格式不合法"}

    if api_base:
        if not re.match(r"^https?://[A-Za-z0-9._\-:/?#=&%]{1,256}$", api_base):
            return {"success": False, "error": "API Base URL 格式不合法"}
        from urllib.parse import urlparse
        try:
            parsed = urlparse(api_base)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return {"success": False, "error": "API Base URL 格式不合法"}
        except Exception:
            return {"success": False, "error": "API Base URL 解析失败"}

    import os
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    env_real = os.path.realpath(env_path)
    project_root = os.path.realpath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    if not env_real.startswith(project_root + os.sep) and env_real != project_root:
        return {"success": False, "error": "非法的 .env 路径"}

    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    env_map = {}
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            if re.match(r"^[A-Z][A-Z0-9_]{1,63}$", k):
                env_map[k] = v.strip()

    def _escape_env_value(v: str) -> str:
        if any(c in v for c in ['\n', '\r', '"', "'", '$', '`', '\\']):
            return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
        return v

    env_map["BMP_LLM_DEFAULT_MODEL"] = model
    if api_key:
        env_map["BMP_LLM_API_KEY"] = api_key
    if api_base:
        env_map["BMP_LLM_API_BASE"] = api_base

    tmp_path = env_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(f"# BidMaster Pro - LLM Configuration\n")
        f.write(f"# Last updated by set_default_model\n")
        for k, v in env_map.items():
            f.write(f"{k}={_escape_env_value(v)}\n")
    os.replace(tmp_path, env_path)
    try:
        os.chmod(env_path, 0o600)
    except Exception:
        pass

    from services.llm_factory import reset_llm_gateway
    reset_llm_gateway()

    return {"success": True, "model": model}
