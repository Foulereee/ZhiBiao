from __future__ import annotations

from core.llm_gateway.gateway import LLMGateway
from core.settings import get_settings

_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        settings = get_settings()
        _gateway = LLMGateway({
            "providers": [
                {
                    "api_key": settings.llm_api_key,
                    "api_base": settings.llm_api_base,
                }
            ],
            "default_model": settings.llm_default_model,
            "fallback_models": [m.strip() for m in settings.llm_fallback_modes.split(",") if m.strip()],
            "max_retries": settings.llm_max_retries,
        })
    return _gateway


def reset_llm_gateway():
    global _gateway
    _gateway = None
