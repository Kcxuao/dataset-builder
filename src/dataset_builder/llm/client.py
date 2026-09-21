"""Validated JSON responses over an OpenAI Compatible Chat Completions API."""

import asyncio
import json
import re
from typing import Protocol, TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
)
from pydantic import BaseModel, SecretStr, ValidationError

from dataset_builder.config import LLMSettings
from dataset_builder.models import Message

T = TypeVar("T", bound=BaseModel)
CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)


class LLMResponseError(ValueError):
    """The service returned no usable JSON or an invalid response model."""


class QuotaExceededError(ValueError):
    """The provider rejected a request because the account has no usable quota."""


def is_quota_error(error: Exception) -> bool:
    text = str(error).lower()
    markers = ("insufficient_quota", "insufficient quota", "余额不足", "额度不足", "credit")
    return any(marker in text for marker in markers)


class LLMClient(Protocol):
    async def generate(self, messages: list[Message], response_model: type[T]) -> T: ...


class OpenAICompatibleModelCatalog:
    """Fetch the temporary model list exposed by a compatible service."""

    def __init__(
        self, base_url: str, api_key: SecretStr, timeout: float, sdk: AsyncOpenAI | None = None,
    ) -> None:
        self._sdk = sdk or AsyncOpenAI(
            api_key=api_key.get_secret_value(), base_url=base_url, timeout=timeout, max_retries=0,
        )
        self._owns_sdk = sdk is None

    async def list_models(self) -> list[dict[str, str]]:
        try:
            response = await self._sdk.models.list()
        except AuthenticationError as exc:
            raise ValueError("API Key 无效或没有读取模型列表的权限") from exc
        except (APITimeoutError, APIConnectionError) as exc:
            raise ValueError("无法连接模型服务，请检查接口地址、网络和超时设置") from exc
        except APIStatusError as exc:
            raise ValueError(f"模型服务返回错误状态：{exc.status_code}") from exc

        models: dict[str, dict[str, str]] = {}
        for item in response.data:
            model_id = getattr(item, "id", "")
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            owned_by = getattr(item, "owned_by", "")
            entry = {"id": model_id.strip()}
            if isinstance(owned_by, str) and owned_by.strip():
                entry["owned_by"] = owned_by.strip()
            models[entry["id"]] = entry
        if not models:
            raise ValueError("服务未返回可用模型，请手动填写模型名称")
        return [models[model_id] for model_id in sorted(models, key=str.casefold)]

    async def aclose(self) -> None:
        if self._owns_sdk:
            await self._sdk.close()


def parse_response[T: BaseModel](content: str | None, response_model: type[T]) -> T:
    if not content or not content.strip():
        raise LLMResponseError("模型未返回正文")
    text = content.strip()
    fence = CODE_FENCE.fullmatch(text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMResponseError("模型返回的内容不是完整的 JSON；请启用 JSON 模式或提高输出上限") from exc
    try:
        return response_model.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(sorted({".".join(map(str, error["loc"])) for error in exc.errors()}))
        raise LLMResponseError(f"模型返回的 JSON 结构不符合要求，问题字段：{fields}") from exc


class OpenAICompatibleClient:
    def __init__(self, settings: LLMSettings, sdk: AsyncOpenAI | None = None) -> None:
        self.settings = settings
        self._sdk = sdk or AsyncOpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.timeout,
            max_retries=0,
        )
        self._owns_sdk = sdk is None
        self._semaphore = asyncio.Semaphore(settings.concurrency_limit)

    async def generate(self, messages: list[Message], response_model: type[T]) -> T:
        async with self._semaphore:
            for attempt in range(self.settings.max_retries + 1):
                try:
                    arguments = dict(
                        model=self.settings.model,
                        messages=[message.model_dump() for message in messages],
                        temperature=self.settings.temperature,
                        max_tokens=self.settings.max_tokens,
                    )
                    if self.settings.json_mode:
                        arguments["response_format"] = {"type": "json_object"}
                    if self.settings.thinking is not None:
                        arguments["extra_body"] = {
                            "thinking": {"type": "enabled" if self.settings.thinking else "disabled"}
                        }
                    completion = await self._sdk.chat.completions.create(**arguments)
                    if not completion.choices:
                        raise LLMResponseError("模型没有返回候选结果")
                    choice = completion.choices[0]
                    if getattr(choice, "finish_reason", None) == "length":
                        raise LLMResponseError(
                            f"模型输出达到 {self.settings.max_tokens} 个令牌的上限，内容可能被截断；"
                            "请提高 LLM_MAX_TOKENS"
                        )
                    content = choice.message.content
                    if not content or not content.strip():
                        if getattr(choice.message, "reasoning_content", None):
                            raise LLMResponseError("模型只返回了思考内容，没有最终正文；请关闭思考模式或提高输出上限")
                    return parse_response(content, response_model)
                except RateLimitError as exc:
                    if is_quota_error(exc):
                        raise QuotaExceededError("模型服务额度不足，已停止后续请求") from exc
                    if attempt >= self.settings.max_retries:
                        raise
                    await asyncio.sleep(min(0.25 * 2**attempt, 2.0))
                except (APIConnectionError, InternalServerError, LLMResponseError):
                    if attempt >= self.settings.max_retries:
                        raise
                    await asyncio.sleep(min(0.25 * 2**attempt, 2.0))
        raise AssertionError("重试循环应返回结果或抛出异常")

    async def aclose(self) -> None:
        if self._owns_sdk:
            await self._sdk.close()
