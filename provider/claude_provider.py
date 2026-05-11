from __future__ import annotations

import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from agent.hook import (
    EVENT_AFTER_MODEL_CALL,
    EVENT_BEFORE_MODEL_CALL,
    HookBus,
)

from .base import BaseModelProvider


class ClaudeProvider(BaseModelProvider):
    """基于 Anthropic Claude API 的模型提供者。

    响应会被归一化为 OpenAI ChatCompletion 格式，以兼容上层消费方。
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        hooks: HookBus | None = None,
    ):
        from anthropic import AsyncAnthropic

        super().__init__(model=model, api_key=api_key, api_base=api_base, hooks=hooks)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        self.base_url = api_base or os.getenv("ANTHROPIC_API_BASE") or os.getenv("OPENAI_API_BASE", None)
        self.client = AsyncAnthropic(api_key=self.api_key, base_url=self.base_url)

    @staticmethod
    def _convert_messages(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        """将 OpenAI 格式消息列表拆分为 Claude 的 (system, messages)。"""
        system: str | None = None
        converted: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system = content
            else:
                converted.append({"role": role, "content": content})
        return system, converted

    @staticmethod
    def _normalize_response(raw: Any) -> SimpleNamespace:
        """将 Claude 响应归一化为 OpenAI ChatCompletion 格式。"""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in raw.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": block.input,
                    },
                })

        content = "\n".join(text_parts)
        message = SimpleNamespace(content=content, tool_calls=tool_calls or None)
        choice = SimpleNamespace(message=message, finish_reason=getattr(raw, "stop_reason", None))
        return SimpleNamespace(choices=[choice], id=getattr(raw, "id", None))

    async def call_model(self, messages: list[dict[str, Any]], *, enable_thinking: bool = False) -> Any:
        if self.hooks:
            await self.hooks.emit(
                EVENT_BEFORE_MODEL_CALL,
                {"model": self.model, "messages": messages, "enable_thinking": enable_thinking},
            )

        system, claude_messages = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": claude_messages,
            "max_tokens": 8192,
        }
        if system:
            kwargs["system"] = system
        if enable_thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 4096}

        try:
            raw = await self.client.messages.create(**kwargs)
        except Exception as exc:
            if self.hooks:
                await self.hooks.emit(
                    EVENT_AFTER_MODEL_CALL,
                    {"model": self.model, "error": str(exc)},
                )
            raise

        response = self._normalize_response(raw)

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

        system, claude_messages = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": claude_messages,
            "max_tokens": 8192,
        }
        if system:
            kwargs["system"] = system
        if enable_thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 4096}

        try:
            async with self.client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
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
                {"model": self.model, "stream": True},
            )
