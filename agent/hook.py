import inspect
from typing import Any, Awaitable, Callable

HookHandler = Callable[[dict[str, Any]], Awaitable[None] | None]

EVENT_REQUEST_START = "on_request_start"
EVENT_REQUEST_END = "on_request_end"
EVENT_BEFORE_RETRIEVAL = "before_retrieval"
EVENT_AFTER_RETRIEVAL = "after_retrieval"
EVENT_BEFORE_MODEL_CALL = "before_model_call"
EVENT_AFTER_MODEL_CALL = "after_model_call"
EVENT_BEFORE_TOOL_EXECUTE = "before_tool_execute"
EVENT_AFTER_TOOL_EXECUTE = "after_tool_execute"


class HookBus:
    """Minimal hook bus for registering and emitting lifecycle events."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[HookHandler]] = {}

    def register(self, event: str, handler: HookHandler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def on(self, event: str, handler: HookHandler) -> None:
        self.register(event, handler)

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        handlers = self._handlers.get(event, [])
        if not handlers:
            return
        for handler in handlers:
            try:
                result = handler(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # Hooks should never break the main flow.
                continue