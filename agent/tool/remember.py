from pathlib import Path
from typing import Any

from .tool import Tool
from ..memory import MemoryManager


class RememberTool(Tool):
    @property
    def name(self) -> str:
        return "remember"

    @property
    def description(self) -> str:
        return "Add a note to the agent's long-term memory in MEMORY.md."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": "The text that should be added to long-term memory."
                }
            },
            "required": ["note"],
        }

    def __init__(self, workspace: Path, memory_manager: MemoryManager):
        super().__init__(workspace)
        self.memory_manager = memory_manager

    async def execute(self, note: str, **kwargs: Any) -> str:
        if not note.strip():
            return "Error: note cannot be empty."

        self.memory_manager.append_memory(note)
        return f"记住了: {note}"
