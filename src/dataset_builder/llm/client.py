"""Validated JSON responses over an OpenAI Compatible Chat Completions API."""

import asyncio
import json
import re
from typing import Protocol, TypeVar

from openai import APIConnectionError, AsyncOpenAI, InternalServerError, RateLimitError
from pydantic import BaseModel, ValidationError

from dataset_builder.config import LLMSettings
from dataset_builder.models import Message

T = TypeVar("T", bound=BaseModel)
CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)


class LLMResponseError(ValueError):
    """The service returned no usable JSON or an invalid response model."""


class LLMClient(Protocol):
    async def generate(self, messages: list[Message], response_model: type[T]) -> T: ...


def parse_response[T: BaseModel](content: str | None, response_model: type[T]) -> T:
    if not content:
        raise LLMResponseError("LLM response is empty")
    text = content.strip()
    fence = CODE_FENCE.fullmatch(text)
    if fence:
        text = fence.group(1).strip()
    try:
        return response_model.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMResponseError("LLM response is not valid JSON for the expected schema") from exc


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
                    completion = await self._sdk.chat.completions.create(
                        model=self.settings.model,
                        messages=[message.model_dump() for message in messages],
                        temperature=self.settings.temperature,
                        max_tokens=self.settings.max_tokens,
                    )
                    content = completion.choices[0].message.content if completion.choices else None
                    return parse_response(content, response_model)
                except (APIConnectionError, RateLimitError, InternalServerError, LLMResponseError):
                    if attempt >= self.settings.max_retries:
                        raise
                    await asyncio.sleep(min(0.25 * 2**attempt, 2.0))
        raise AssertionError("retry loop must return or raise")

    async def aclose(self) -> None:
        if self._owns_sdk:
            await self._sdk.close()
