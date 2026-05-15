from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import AgentConfig
from services.llm_factory import get_llm_gateway

router = APIRouter()


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


@router.put("/default-model")
async def set_default_model(config: dict, db: AsyncSession = Depends(get_db)):
    model = config.get("model", "")
    api_key = config.get("api_key", "")
    api_base = config.get("api_base", "")

    if not model:
        return {"success": False, "error": "模型不能为空"}

    import os
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")

    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    env_map = {}
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env_map[k.strip()] = v.strip()

    env_map["BMP_LLM_DEFAULT_MODEL"] = model
    if api_key:
        env_map["BMP_LLM_API_KEY"] = api_key
    if api_base:
        env_map["BMP_LLM_API_BASE"] = api_base

    with open(env_path, "w", encoding="utf-8") as f:
        for k, v in env_map.items():
            f.write(f"{k}={v}\n")

    from services.llm_factory import reset_llm_gateway
    reset_llm_gateway()

    return {"success": True, "model": model}
