from pathlib import Path

from .tool import Tool

def resolve_path(path: str, workspace: Path) -> Path:
    p = (workspace / path).resolve()
    if workspace not in p.parents and p != workspace:
        raise ValueError("禁止访问工作目录外的文件")
    return p

class ReadFileTool(Tool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file under the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs) -> str:
        p = resolve_path(path, self.workspace)
        if not p.exists() or not p.is_file():
            return f"Error: 文件不存在: {path}"
        return p.read_text(encoding="utf-8")

class WriteFileTool(Tool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file under the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs) -> str:
        p = resolve_path(path, self.workspace)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {path}，字节数 {len(content)}"

class ListDirTool(Tool):
    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List files in a workspace directory."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs) -> str:
        p = resolve_path(path, self.workspace)
        if not p.exists() or not p.is_dir():
            return f"Error: 目录不存在: {path}"
        return "\n".join(sorted(item.name for item in p.iterdir()))

class CreateTool(Tool):
    @property
    def name(self) -> str:
        return "create"

    @property
    def description(self) -> str:
        return "Create a file or directory under the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to create (file or directory)."
                },
                "is_directory": {
                    "type": "boolean",
                    "description": "Whether to create a directory (true) or file (false).",
                    "default": False
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file (only used if is_directory is false).",
                    "default": ""
                }
            },
            "required": ["path"],
        }

    async def execute(self, path: str, is_directory: bool = False, content: str = "", **kwargs) -> str:
        full_path = resolve_path(path, self.workspace)
        if is_directory:
            full_path.mkdir(parents=True, exist_ok=True)
            return f"Created directory: {path}"
        else:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            return f"Created file: {path} with {len(content)} bytes"
