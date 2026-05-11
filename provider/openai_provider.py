import os
from collections.abc import AsyncIterator
from typing import Any

from agent.hook import (
    EVENT_AFTER_MODEL_CALL,
    EVENT_BEFORE_MODEL_CALL,
    HookBus,
)

from .base import BaseModelProvider


class OpenAIProvider(BaseModelProvider):
    """基于 OpenAI 兼容接口的模型提供者。"""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        hooks: HookBus | None = None,
    ):
        from openai import AsyncOpenAI

        super().__init__(model=model, api_key=api_key, api_base=api_base, hooks=hooks)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = api_base or os.getenv("OPENAI_API_BASE", None)
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def call_model(self, messages: list[dict[str, Any]], *, enable_thinking: bool = False) -> Any:
        if self.hooks:
            await self.hooks.emit(
                EVENT_BEFORE_MODEL_CALL,
                {"model": self.model, "messages": messages, "enable_thinking": enable_thinking},
            )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                extra_body={"enable_thinking": enable_thinking},
            )
        except Exception as exc:
            if self.hooks:
                await self.hooks.emit(
                    EVENT_AFTER_MODEL_CALL,
                    {"model": self.model, "error": str(exc)},
                )
            raise
        if self.hooks:
            await self.hooks.emit(
                EVENT_AFTER_MODEL_CALL,
                {"model": self.model, "response": response},
            )
        return response

    async def call_model_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        enable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        if self.hooks:
            await self.hooks.emit(
                EVENT_BEFORE_MODEL_CALL,
                {"model": self.model, "messages": messages, "enable_thinking": enable_thinking, "stream": True},
            )
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                extra_body={"enable_thinking": enable_thinking},
            )
        except Exception as exc:
            if self.hooks:
                await self.hooks.emit(
                    EVENT_AFTER_MODEL_CALL,
                    {"model": self.model, "error": str(exc)},
                )
            raise
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content
        if self.hooks:
            await self.hooks.emit(
                EVENT_AFTER_MODEL_CALL,
                {"model": self.model, "stream": True},
            )
