from __future__ import annotations

import abc
import os
from collections.abc import AsyncIterator
from typing import Any

from agent.hook import HookBus


class BaseModelProvider(abc.ABC):
    """所有模型提供者的抽象基类。"""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        hooks: HookBus | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or ""
        self.api_base = api_base
        self.hooks = hooks

    @abc.abstractmethod
    async def call_model(
        self,
        messages: list[dict[str, Any]],
        *,
        enable_thinking: bool = False,
    ) -> Any:
        """调用模型并返回响应（格式需兼容 OpenAI ChatCompletion）。"""

    @abc.abstractmethod
    async def call_model_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        enable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        """流式调用模型，逐 token yield 文本内容。"""


class ProviderManager:
    """根据环境变量管理并创建模型提供者。

    通过 PROVIDER_TYPE 环境变量切换：
    - "claude" → ClaudeProvider（读取 ANTHROPIC_* 环境变量）
    - 其他/未设置 → OpenAIProvider（读取 OPENAI_* 环境变量）
    """

    _PROVIDER_MAP: dict[str, str] = {
        "openai": "OPENAI",
        "claude": "ANTHROPIC",
    }

    def __init__(self, hooks: HookBus | None = None) -> None:
        self._hooks = hooks
        self._ptype = os.getenv("PROVIDER_TYPE", "openai").strip().lower()

    @property
    def provider_type(self) -> str:
        return self._ptype

    def _env(self, suffix: str) -> str:
        """按当前 provider 读取对应前缀的环境变量。"""
        prefix = self._PROVIDER_MAP.get(self._ptype, "OPENAI")
        return os.getenv(f"{prefix}_{suffix}", "").strip()

    def create(self) -> BaseModelProvider:
        model = self._env("MODEL_NAME")
        api_key = self._env("API_KEY")
        api_base = self._env("API_BASE")

        if not model:
            raise RuntimeError(f"{self._PROVIDER_MAP.get(self._ptype, 'OPENAI')}_MODEL_NAME is not set")
        if not api_key:
            raise RuntimeError(f"{self._PROVIDER_MAP.get(self._ptype, 'OPENAI')}_API_KEY is not set")

        if self._ptype == "claude":
            from .claude_provider import ClaudeProvider
            return ClaudeProvider(model=model, api_key=api_key, api_base=api_base, hooks=self._hooks)

        from .openai_provider import OpenAIProvider
        return OpenAIProvider(model=model, api_key=api_key, api_base=api_base, hooks=self._hooks)
