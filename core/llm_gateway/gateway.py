"""LLM Gateway — 直接使用 OpenAI SDK 调用，绕过 litellm 的参数转发问题。

参考 ai_bidding (requests.post) 和 OpenBidKit (fetch) 的直接调用方式，
改用 openai.AsyncOpenAI 客户端直接调用 OpenAI 兼容 API，
确保 response_format、temperature、max_tokens 等参数被正确传递。
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
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
        self.max_retries = config.get("max_retries", 2)
        self.json_repair = JsonRepairEngine()
        self._token_usage: deque[dict] = deque(maxlen=10000)  # 限制最大存储量，防止内存泄漏

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

        # 单次请求超时(秒):这是"兜底"默认值,长文档生成走它。
        # 检查类技能用更短的 per-request 超时(BMP_LLM_CHECK_TIMEOUT),
        # 因为原值 300s 配合重试链,一个技能最坏能拖到 15 分钟
        # (日志实测: 合规性检查单次调用 749.8s),客户看到的就是"执行检查中"一直转。
        try:
            req_timeout = float(os.environ.get("BMP_LLM_TIMEOUT", "300") or 300)
        except (TypeError, ValueError):
            req_timeout = 300.0

        return AsyncOpenAI(
            api_key=api_key or "sk-placeholder",
            base_url=api_base,
            timeout=req_timeout,  # 单次请求超时,配合上层快速重试
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
        request_timeout: float | None = None,
        no_thinking: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """调用 LLM 获取文本响应。

        关键改进：
        1. 使用 OpenAI SDK 直接调用，确保参数正确传递
        2. response_format 不支持时自动降级重试
        3. 详细的日志记录
        4. no_thinking=True 时带 thinking={"type":"disabled"}:推理模型做 JSON
           抽取这类任务时会把 8192 token 全烧在思考上、content 为空(实测
           finish_reason=length),导致解读/检查类功能直接失败。
        """
        model_name = model or self._resolved_model
        # 默认输出上限,可用 BMP_LLM_MAX_TOKENS 覆盖。
        # 注意:调大上限会显著拉长单次调用(实测 8192→约 90s,16384→约 125s,
        # 而推理型模型打满后重试可拖到 12 分钟)。默认保持 8192,只有确实被
        # "思考"吃光时才会自动提额一次(见下方 empty+打满 分支)。
        try:
            default_max_tokens = int(os.environ.get("BMP_LLM_MAX_TOKENS", "8192") or 8192)
        except (TypeError, ValueError):
            default_max_tokens = 8192
        effective_max_tokens = max_tokens or default_max_tokens

        last_error = None
        # 因"思考吃光预算"而提额重试时,锁定同一个模型,避免顺手切到别家模型
        pinned_model: str | None = None
        for attempt in range(self.max_retries):
            # 每次尝试可能使用不同的模型（降级）
            current_model = pinned_model or self._get_model_for_attempt(attempt, model_name)

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
                # 单次调用超时可按调用覆盖:检查类技能用短超时(快速失败),
                # 长文档生成仍用客户端默认的宽松超时,避免误杀
                if request_timeout:
                    kwargs["timeout"] = request_timeout

                if stream:
                    response = await self._client.chat.completions.create(**kwargs, stream=True)
                    logger.info(f"[LLM] 流式响应开始 model={current_model}")
                    return self._stream_response(response)

                _extra = {}
                if no_thinking and getattr(self, "_thinking_mode", "auto") != "unsupported":
                    _extra = {"thinking": {"type": "disabled"}}
                try:
                    response = await self._client.chat.completions.create(
                        **kwargs, **({"extra_body": _extra} if _extra else {})
                    )
                except Exception as _pe:  # noqa: BLE001
                    _m = str(_pe).lower()
                    if _extra and ("400" in _m or "invalid" in _m or "unknown" in _m or "unexpected" in _m):
                        self._thinking_mode = "unsupported"
                        logger.warning("[LLM] provider 不认 thinking 参数,后续不再携带: %s", _pe)
                        response = await self._client.chat.completions.create(**kwargs)
                    else:
                        raise
                choice = response.choices[0]
                content = choice.message.content or ""
                finish_reason = str(getattr(choice, "finish_reason", "") or "")
                reasoning = getattr(choice.message, "reasoning_content", None) or ""

                # 推理型模型可能把内容全放在 reasoning_content 里、content 留空
                if not content and reasoning:
                    logger.warning(
                        f"[LLM] content 为空但存在 reasoning_content("
                        f"{len(reasoning)}字符), finish_reason={finish_reason}, 改用它作为回答"
                    )
                    content = reasoning

                # 预算被"思考"吃光、一个字都没留下:提高 max_tokens 重试。
                # 只允许提额一次且总耗时不能超过 150s,否则一个技能最坏会拖到十几分钟
                # (日志实测: 一次合规性检查 749.8s,用户反馈"检查中时间特别长")。
                elapsed_so_far = time.monotonic() - t0
                if (
                    not content
                    and response.usage
                    and response.usage.completion_tokens >= effective_max_tokens
                    and effective_max_tokens < 32768
                    and elapsed_so_far < 150
                ):
                    new_max = min(effective_max_tokens * 2, 32768)
                    logger.warning(
                        f"[LLM] 输出为空且 max_tokens 已打满 "
                        f"(completion_tokens={response.usage.completion_tokens}, "
                        f"finish_reason={finish_reason}), 提高到 {new_max} 后重试"
                    )
                    effective_max_tokens = new_max
                    pinned_model = current_model
                    # 明确要求"不要思考",否则推理型模型会再次把预算烧在推理上
                    messages = list(messages) + [
                        {
                            "role": "user",
                            "content": (
                                "请直接输出最终答案，不要输出或展开任何思考、推理过程，"
                                "不要复述题目或要求。若需要 JSON，请一次性给出完整 JSON。"
                            ),
                        }
                    ]
                    continue

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
        request_timeout: float | None = None,
        no_thinking: bool = True,
    ) -> dict:
        """调用 LLM 获取 JSON 响应，带修复和校验。

        改进：
        1. 增加重试机制（最多3次尝试，与 OpenBidKit 一致）
        2. 每次 LLM 调用都强制 response_format=json_object
        3. 详细的日志记录
        4. 支持 max_tokens 参数控制输出长度
        5. no_thinking 默认 True:JSON 抽取不需要长思考,开着思考会让推理模型
           把 token 全用在 reasoning 上、content 返回空 —— 招标解读"AI 解读失败"
           的根因就是这个。
        """
        t0 = time.monotonic()
        logger.info(
            f"[LLM.collect_json] 开始 model={model or self._resolved_model}, "
            f"temperature={temperature}, max_repair={max_repair_attempts}, "
            f"max_tokens={max_tokens or 'default'}"
        )

        max_attempts = 2  # 1次正常 + 1次重试，降低尾部延迟
        last_error = None
        working_messages = list(messages)

        for attempt in range(max_attempts):
            try:
                response_text = await self.chat(
                    messages=working_messages,
                    model=model,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=max_tokens,
                    request_timeout=request_timeout,
                    no_thinking=no_thinking,
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

                # 部分模型(尤其小参数模型)会把 response_format 参数原样回显成
                # {"type": "json_object"},或干脆回 {}。这类结果"解析成功"但没有任何
                # 检查内容,以前会被当成有效结果写进报告,客户看到一份空报告却写着
                # "✅ 通过"。这里直接判为无效并纠偏重试。
                if self._looks_degenerate(result):
                    logger.warning(
                        f"[LLM.collect_json] 模型返回空壳 JSON: {str(result)[:150]}"
                    )
                    if attempt < max_attempts - 1:
                        working_messages = list(messages) + [
                            {
                                "role": "user",
                                "content": (
                                    "你上一次只回了一个空壳 JSON（例如 {\"type\": \"json_object\"}），"
                                    "没有包含任何检查内容。请重新作答：只输出一个真实、完整、非空的 JSON 对象，"
                                    "所有字段值必须是根据给定材料得出的实际结论；不要回显 response_format 之类的参数，"
                                    "不要输出空对象或空数组。"
                                ),
                            }
                        ]
                        last_error = LLMGatewayError("模型返回空壳 JSON（无任何有效内容）")
                        continue
                    raise LLMGatewayError("模型返回空壳 JSON（无任何有效内容）")

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
        max_tokens: int | None = None,
        no_thinking: bool = False,
    ) -> AsyncGenerator[str, None]:
        """流式聊天，带错误处理和重试。

        max_tokens 不传时保持历史行为(8192)。生成正文时会按"本章目标字数"
        传进来,否则 8192 的硬顶会让单章随便写到 1.1 万字。

        no_thinking=True 带 thinking={"type":"disabled"}:实测商汤
        sensenova-6.8-flash-lite 这类推理模型写长章节时会把上万 token 全用在
        思考上,finish_reason=length 而正文一个字都没开始写(流里 0 个内容块),
        导致 181/303 章落到兜底文案。关闭思考后 reasoning_tokens 直接归零。
        provider 不认该参数(400)时自动去掉并记住,不影响别的模型。

        改进：
        1. 外层 try/except 捕获流式传输中的所有异常
        2. 流式中断时尝试重新发起请求（最多重试 max_retries 次）
        3. 重试时会带上已收集的内容作为前缀提示，避免重复生成
        """
        model_name = model or self._resolved_model
        collected_chunks: list[str] = []
        last_error = None

        for attempt in range(self.max_retries):
            current_model = self._get_model_for_attempt(attempt, model_name)
            try:
                # 如果是重试且有已收集内容，将已收集内容注入 messages
                retry_messages = messages
                if attempt > 0 and collected_chunks:
                    prefix = "".join(collected_chunks)
                    retry_messages = messages + [
                        {"role": "assistant", "content": prefix},
                        {"role": "user", "content": "请继续从上次中断的地方继续输出，不要重复已输出的内容。"},
                    ]
                    logger.info(
                        f"[LLM.stream_chat] 重试 attempt={attempt+1}, "
                        f"已收集{len(prefix)}字符, 将请求续写"
                    )

                # 关闭推理:带 thinking={"type":"disabled"}。provider 不认就永久去掉。
                _extra = {}
                if no_thinking and getattr(self, "_thinking_mode", "auto") != "unsupported":
                    _extra = {"thinking": {"type": "disabled"}}
                try:
                    response = await self._client.chat.completions.create(
                        model=current_model,
                        messages=retry_messages,
                        temperature=temperature,
                        max_tokens=max_tokens or 8192,
                        stream=True,
                        **({"extra_body": _extra} if _extra else {}),
                    )
                except Exception as _pe:  # noqa: BLE001
                    _msg = str(_pe).lower()
                    if _extra and ("400" in _msg or "invalid" in _msg or "unknown" in _msg or "unexpected" in _msg):
                        self._thinking_mode = "unsupported"
                        logger.warning("[LLM] provider 不认 thinking 参数,后续不再携带: %s", _pe)
                        response = await self._client.chat.completions.create(
                            model=current_model,
                            messages=retry_messages,
                            temperature=temperature,
                            max_tokens=max_tokens or 8192,
                            stream=True,
                        )
                    else:
                        raise
                logger.info(f"[LLM] 流式响应开始 model={current_model}, attempt={attempt+1}")

                # 消费流式响应
                async for chunk in self._stream_response(response):
                    collected_chunks.append(chunk)
                    yield chunk

                # 流式正常完成
                return

            except (APITimeoutError, APIConnectionError, APIError) as e:
                last_error = e
                logger.error(
                    f"[LLM.stream_chat] 流式中断 model={current_model}, "
                    f"attempt={attempt+1}/{self.max_retries}, 已收集{len(collected_chunks)}个chunk, "
                    f"错误={str(e)[:200]}"
                )
                if attempt < self.max_retries - 1:
                    logger.info(f"[LLM.stream_chat] 准备重试...")
                    continue
            except Exception as e:
                last_error = e
                logger.error(f"[LLM.stream_chat] 未知异常: {e}")
                if attempt < self.max_retries - 1:
                    # 429(rpm exhausted)是分钟级配额:必须等,否则三次重试挤在同一分钟里全部失败。
                    _m = str(e).lower()
                    _wait = 25 * (attempt + 1) if ("429" in _m or "rpm" in _m or "quota" in _m) else 2 * (attempt + 1)
                    logger.warning(f"[LLM.stream_chat] 第 {attempt + 1} 次失败, 等待 {_wait}s 后重试")
                    await asyncio.sleep(_wait)
                    continue

        # 所有重试用尽
        if last_error:
            logger.error(f"[LLM.stream_chat] 所有重试失败: {last_error}")
            raise LLMGatewayError(f"流式聊天所有重试失败: {last_error}") from last_error

    def _get_model_for_attempt(self, attempt: int, original_model: str) -> str:
        """根据重试次数选择模型（支持降级）。

        兜底模型必须与当前 provider 同源:原先 BMP_LLM_FALLBACK_MODES=ollama/qwen2.5
        被无差别套在商汤客户端(https://token.sensenova.cn/v1)上,重试必然返回
        404 "model is not found",把本来能成功的重试一起拖死。这里只接受同源兜底。
        """
        if attempt == 0 or not self.fallback_models:
            return original_model
        origin_prefix = original_model.split("/", 1)[0] if "/" in original_model else ""
        compat = [
            f for f in self.fallback_models
            if "/" not in f or f.split("/", 1)[0] == origin_prefix
        ]
        if not compat:
            logger.warning(
                f"[LLM] 兜底模型 {self.fallback_models} 与当前 model={original_model} 不同源,"
                "跳过降级,继续用原模型重试"
            )
            return original_model
        idx = min(attempt - 1, len(compat) - 1)
        return self._strip_provider_prefix(compat[idx])

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

    @staticmethod
    def _looks_degenerate(payload: object) -> bool:
        """判断模型是否只回了一个没有任何内容的空壳 JSON。

        典型形态是模型把 response_format 参数原样回显:{"type": "json_object"},
        或直接回 {}/空数组。这类结果 JSON 解析"成功",但技能层会把它当成
        "检查通过"写进报告,客户看到的是一份空报告 + "✅ 通过"。
        """
        if payload is None:
            return True
        if not isinstance(payload, dict):
            return False
        if not payload:
            return True
        meta_only = {
            "type", "json_object", "response_format", "format",
            "schema", "code", "additionalproperties",
        }
        real = {
            k: v for k, v in payload.items()
            if str(k).strip().lower() not in meta_only
        }
        if not real:
            return True
        return all(v is None or v == "" or v == [] or v == {} for v in real.values())

    async def _stream_response(self, response) -> AsyncGenerator[str, None]:
        """流式响应处理，带错误恢复。

        改进：
        1. 捕获流式迭代中的异常，避免直接终止生成器
        2. 对空 choices 做防御处理
        3. 遇到错误时 yield 特殊标记，让上层感知
        """
        try:
            async for chunk in response:
                try:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
                except (IndexError, AttributeError) as e:
                    logger.warning(f"[LLM._stream_response] chunk解析异常(已跳过): {e}")
                    continue
        except (APITimeoutError, APIConnectionError, APIError) as e:
            logger.error(f"[LLM._stream_response] 流式传输中断: {e}")
            # 向上层发出错误信号，而不是静默终止
            raise
        except Exception as e:
            logger.error(f"[LLM._stream_response] 未知错误: {e}")
            raise

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
        max_tokens: int | None = None,
    ) -> ToolCallResponse:
        """支持 function calling 的聊天接口"""
        model_name = model or self._resolved_model
        effective_max_tokens = max_tokens or 8192

        kwargs: dict = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
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
