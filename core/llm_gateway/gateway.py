"""LLM Gateway — 直接使用 OpenAI SDK 调用，绕过 litellm 的参数转发问题。

参考 ai_bidding (requests.post) 和 OpenBidKit (fetch) 的直接调用方式，
改用 openai.AsyncOpenAI 客户端直接调用 OpenAI 兼容 API，
确保 response_format、temperature、max_tokens 等参数被正确传递。
"""

import json
import logging
import time
from typing import AsyncGenerator, Any, Callable

from openai import AsyncOpenAI, APIError, APITimeoutError, APIConnectionError

from core.llm_gateway.json_repair import JsonRepairEngine
from core.exceptions import LLMGatewayError
from core.agent_framework.types import ToolCallItem, ToolCallResponse

logger = logging.getLogger(__name__)


class LLMGateway:
    def __init__(self, config: dict):
        self.providers = config.get("providers", [])
        self.default_model = config.get("default_model", "deepseek/deepseek-chat")
        self.fallback_models = config.get("fallback_models", [])
        self.max_retries = config.get("max_retries", 3)
        self.json_repair = JsonRepairEngine()
        self._token_usage: list[dict] = []

        # 从 default_model 中提取实际模型名（去掉 provider 前缀）
        self._resolved_model = self._strip_provider_prefix(self.default_model)

        # 构建 OpenAI 客户端
        self._client = self._build_client()

    @staticmethod
    def _strip_provider_prefix(model: str) -> str:
        """去掉 litellm 风格的 provider 前缀，如 'deepseek/deepseek-chat' -> 'deepseek-chat'"""
        known_prefixes = {
            "deepseek", "openai", "ollama", "zhipu", "dashscope",
            "azure", "anthropic", "cohere", "huggingface", "vertex_ai",
            "gemini", "mistral", "groq", "together_ai", "replicate",
        }
        if "/" in model:
            prefix, rest = model.split("/", 1)
            if prefix in known_prefixes:
                return rest
        return model

    def _build_client(self) -> AsyncOpenAI:
        """根据配置构建 OpenAI AsyncClient"""
        api_key = ""
        api_base = "https://api.openai.com/v1"
        if self.providers:
            provider = self.providers[0]
            api_key = provider.get("api_key") or ""
            api_base = provider.get("api_base") or api_base

        # 确保 api_base 以 /v1 结尾（兼容不同格式）
        if api_base and not api_base.rstrip("/").endswith("/v1"):
            api_base = api_base.rstrip("/") + "/v1"

        return AsyncOpenAI(
            api_key=api_key or "sk-placeholder",
            base_url=api_base,
            timeout=300.0,  # 5分钟总超时，与 OpenBidKit 一致
            max_retries=0,  # 我们自己控制重试
        )

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        stream: bool = False,
        response_format: dict | None = None,
        max_tokens: int | None = None,
    ) -> str | AsyncGenerator[str, None]:
        """调用 LLM 获取文本响应。

        关键改进：
        1. 使用 OpenAI SDK 直接调用，确保参数正确传递
        2. response_format 不支持时自动降级重试
        3. 详细的日志记录
        """
        model_name = model or self._resolved_model
        effective_max_tokens = max_tokens or 8192

        last_error = None
        for attempt in range(self.max_retries):
            # 每次尝试可能使用不同的模型（降级）
            current_model = self._get_model_for_attempt(attempt, model_name)

            try:
                t0 = time.monotonic()
                logger.info(
                    f"[LLM] 请求开始 model={current_model}, "
                    f"attempt={attempt+1}/{self.max_retries}, "
                    f"messages={len(messages)}条, temperature={temperature}, "
                    f"max_tokens={effective_max_tokens}, "
                    f"response_format={response_format}, stream={stream}"
                )

                # 构建 kwargs
                kwargs: dict = {
                    "model": current_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": effective_max_tokens,
                }
                if response_format:
                    kwargs["response_format"] = response_format

                if stream:
                    response = await self._client.chat.completions.create(**kwargs, stream=True)
                    logger.info(f"[LLM] 流式响应开始 model={current_model}")
                    return self._stream_response(response)

                response = await self._client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""

                # 记录 token 使用量
                if response.usage:
                    self._record_usage(current_model, response.usage)
                    usage_info = (
                        f"prompt_tokens={response.usage.prompt_tokens}, "
                        f"completion_tokens={response.usage.completion_tokens}"
                    )
                else:
                    usage_info = "usage=N/A"

                elapsed = time.monotonic() - t0
                logger.info(
                    f"[LLM] 请求完成 model={current_model}, "
                    f"耗时={elapsed:.2f}s, "
                    f"输出长度={len(content)}字符, {usage_info}"
                )
                return content

            except (APIError, APITimeoutError, APIConnectionError) as e:
                elapsed = time.monotonic() - t0
                error_msg = str(e)

                # 检查是否是 response_format 不支持的错误
                if response_format and self._is_response_format_error(e):
                    logger.warning(
                        f"[LLM] response_format 不支持，去掉后重试 model={current_model}"
                    )
                    try:
                        kwargs_no_fmt = {k: v for k, v in kwargs.items() if k != "response_format"}
                        response = await self._client.chat.completions.create(**kwargs_no_fmt)
                        content = response.choices[0].message.content or ""
                        if response.usage:
                            self._record_usage(current_model, response.usage)
                        elapsed = time.monotonic() - t0
                        logger.info(
                            f"[LLM] 降级请求完成(无response_format) model={current_model}, "
                            f"耗时={elapsed:.2f}s, 输出长度={len(content)}字符"
                        )
                        return content
                    except Exception as fallback_err:
                        logger.error(f"[LLM] 降级请求也失败: {fallback_err}")
                        last_error = fallback_err
                        continue

                logger.error(
                    f"[LLM] 请求失败 model={current_model}, "
                    f"attempt={attempt+1}/{self.max_retries}, "
                    f"耗时={elapsed:.2f}s, 错误={error_msg[:200]}"
                )
                last_error = e
                continue

            except Exception as e:
                elapsed = time.monotonic() - t0
                logger.error(
                    f"[LLM] 未知异常 model={current_model}, "
                    f"attempt={attempt+1}/{self.max_retries}, "
                    f"耗时={elapsed:.2f}s, 错误={str(e)[:200]}"
                )
                last_error = e
                continue

        raise LLMGatewayError(f"所有重试失败: {last_error}") from last_error

    async def collect_json(
        self,
        messages: list[dict],
        schema: type | None = None,
        validator: Callable | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_repair_attempts: int = 2,
        max_tokens: int | None = None,
    ) -> dict:
        """调用 LLM 获取 JSON 响应，带修复和校验。

        改进：
        1. 增加重试机制（最多3次尝试，与 OpenBidKit 一致）
        2. 每次 LLM 调用都强制 response_format=json_object
        3. 详细的日志记录
        4. 支持 max_tokens 参数控制输出长度
        """
        t0 = time.monotonic()
        logger.info(
            f"[LLM.collect_json] 开始 model={model or self._resolved_model}, "
            f"temperature={temperature}, max_repair={max_repair_attempts}, "
            f"max_tokens={max_tokens or 'default'}"
        )

        max_attempts = 3  # 与 OpenBidKit 一致：1次正常 + 2次重试
        last_error = None

        for attempt in range(max_attempts):
            try:
                response_text = await self.chat(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=max_tokens,
                )

                # 处理流式响应
                if isinstance(response_text, AsyncGenerator):
                    chunks = []
                    try:
                        async for chunk in response_text:
                            chunks.append(chunk)
                    finally:
                        if hasattr(response_text, 'aclose'):
                            await response_text.aclose()
                    response_text = "".join(chunks)

                logger.info(
                    f"[LLM.collect_json] chat完成, "
                    f"attempt={attempt+1}/{max_attempts}, "
                    f"耗时={time.monotonic()-t0:.2f}s, "
                    f"原始文本长度={len(response_text)}字符, "
                    f"前200字符={response_text[:200]}"
                )

                # 尝试解析和修复 JSON
                result = await self.json_repair.repair_and_validate(
                    raw_text=response_text,
                    schema=schema,
                    validator=validator,
                    repair_chat_fn=self.chat,
                    max_attempts=max_repair_attempts,
                )

                logger.info(
                    f"[LLM.collect_json] 全部完成, "
                    f"总耗时={time.monotonic()-t0:.2f}s, "
                    f"结果类型={type(result).__name__}"
                )
                return result

            except Exception as e:
                last_error = e
                logger.warning(
                    f"[LLM.collect_json] 第{attempt+1}次尝试失败: {str(e)[:200]}"
                )
                if attempt < max_attempts - 1:
                    logger.info(f"[LLM.collect_json] 准备第{attempt+2}次重试...")
                    continue

        logger.error(f"[LLM.collect_json] 所有尝试失败: {last_error}")
        raise LLMGatewayError(f"JSON收集失败(重试{max_attempts}次): {last_error}") from last_error

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

    def _get_model_for_attempt(self, attempt: int, original_model: str) -> str:
        """根据重试次数选择模型（支持降级）"""
        if attempt == 0:
            return original_model
        if not self.fallback_models:
            return original_model
        idx = min(attempt - 1, len(self.fallback_models) - 1)
        fallback = self.fallback_models[idx]
        return self._strip_provider_prefix(fallback)

    @staticmethod
    def _is_response_format_error(error: Exception) -> bool:
        """检查是否是 response_format 不支持的错误"""
        error_str = str(error).lower()
        return any(
            keyword in error_str
            for keyword in [
                "response_format",
                "json_object",
                "json mode",
                "not supported",
                "unsupported parameter",
                "invalid_request_error",
            ]
        )

    async def _stream_response(self, response) -> AsyncGenerator[str, None]:
        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
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

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        model: str | None = None,
        temperature: float = 0.3,
    ) -> ToolCallResponse:
        """支持 function calling 的聊天接口"""
        model_name = model or self._resolved_model

        kwargs: dict = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        last_error = None
        for attempt in range(self.max_retries):
            try:
                current_model = self._get_model_for_attempt(attempt, model_name)
                kwargs["model"] = current_model

                response = await self._client.chat.completions.create(**kwargs)
                msg = response.choices[0].message
                self._record_usage(current_model, response.usage)

                if msg.tool_calls:
                    calls = []
                    for tc in msg.tool_calls:
                        calls.append(ToolCallItem(
                            id=tc.id,
                            function_name=tc.function.name,
                            arguments=tc.function.arguments,
                        ))
                    return ToolCallResponse(
                        has_tool_calls=True,
                        tool_calls=calls,
                        content=msg.content or "",
                    )
                return ToolCallResponse(
                    has_tool_calls=False,
                    content=msg.content or "",
                )
            except Exception as e:
                last_error = e
                logger.error(f"[LLM.chat_with_tools] 失败 attempt={attempt+1}: {e}")
                continue

        raise LLMGatewayError(f"chat_with_tools 所有重试失败: {last_error}") from last_error
