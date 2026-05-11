from pathlib import Path

from ..hook import (
    HookBus,
    EVENT_AFTER_TOOL_EXECUTE,
    EVENT_BEFORE_TOOL_EXECUTE,
)

class Tool:
    def __init__(self, workspace: Path):
        self.workspace = workspace
    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def description(self) -> str:
        raise NotImplementedError

    @property
    def parameters(self) -> dict:
        raise NotImplementedError

    def definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    async def execute(self, **kwargs) -> str:
        raise NotImplementedError

class ToolRegistry:
    def __init__(self, hooks: HookBus | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self.hooks = hooks

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' is not registered.")
        return self._tools[name]

    def get_definitions(self) -> list[dict]:
        return [tool.definition() for tool in self._tools.values()]

    async def execute(self, name: str, arguments: dict) -> str:
        try:
            tool = self.get(name)
        except ValueError:
            return f"not support tool '{name}', check tool name and parameters and try again."
        if self.hooks:
            await self.hooks.emit(
                EVENT_BEFORE_TOOL_EXECUTE,
                {"tool": name, "arguments": arguments},
            )
        try:
            result = await tool.execute(**arguments)
            if self.hooks:
                await self.hooks.emit(
                    EVENT_AFTER_TOOL_EXECUTE,
                    {"tool": name, "arguments": arguments, "result": result},
                )
            return result
        except Exception as exc:
            if self.hooks:
                await self.hooks.emit(
                    EVENT_AFTER_TOOL_EXECUTE,
                    {"tool": name, "arguments": arguments, "error": str(exc)},
                )
            return f"Error: tool '{name}' failed: {exc}"
