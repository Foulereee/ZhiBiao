from typing import AsyncGenerator, Any

from litellm import acompletion

from core.llm_gateway.json_repair import JsonRepairEngine
from core.exceptions import LLMGatewayError


class LLMGateway:
    def __init__(self, config: dict):
        self.providers = config.get("providers", [])
        self.default_model = config.get("default_model", "deepseek/deepseek-chat")
        self.fallback_models = config.get("fallback_models", ["ollama/qwen2.5"])
        self.max_retries = config.get("max_retries", 3)
        self.json_repair = JsonRepairEngine()
        self._token_usage: list[dict] = []

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        stream: bool = False,
        response_format: dict | None = None,
    ) -> str | AsyncGenerator[str, None]:
        model = model or self.default_model
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if response_format:
            kwargs["response_format"] = response_format

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await acompletion(**kwargs)
                if stream:
                    return self._stream_response(response)
                content = response.choices[0].message.content or ""
                self._record_usage(model, response.usage)
                return content
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    fallback = self._get_fallback_model(attempt)
                    if fallback:
                        kwargs["model"] = fallback
                continue

        raise LLMGatewayError(f"所有重试失败: {last_error}") from last_error

    async def collect_json(
        self,
        messages: list[dict],
        schema: type | None = None,
        validator: callable | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_repair_attempts: int = 2,
    ) -> dict:
        response_text = await self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        if isinstance(response_text, AsyncGenerator):
            chunks = []
            try:
                async for chunk in response_text:
                    chunks.append(chunk)
            finally:
                if hasattr(response_text, 'aclose'):
                    await response_text.aclose()
            response_text = "".join(chunks)

        return await self.json_repair.repair_and_validate(
            raw_text=response_text,
            schema=schema,
            validator=validator,
            repair_chat_fn=self.chat,
            max_attempts=max_repair_attempts,
        )

    async def stream_chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        result = await self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            stream=True,
        )
        if isinstance(result, AsyncGenerator):
            async for chunk in result:
                yield chunk

    def _get_fallback_model(self, attempt: int) -> str | None:
        if not self.fallback_models:
            return None
        idx = min(attempt, len(self.fallback_models) - 1)
        return self.fallback_models[idx]

    async def _stream_response(self, response) -> AsyncGenerator[str, None]:
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    def _record_usage(self, model: str, usage: Any):
        if usage:
            self._token_usage.append({
                "model": model,
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
            })

    def get_token_summary(self) -> dict:
        total_prompt = sum(u["prompt_tokens"] for u in self._token_usage)
        total_completion = sum(u["completion_tokens"] for u in self._token_usage)
        return {
            "total_requests": len(self._token_usage),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
        }
