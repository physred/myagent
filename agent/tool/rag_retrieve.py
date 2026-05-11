import json
from pathlib import Path
from typing import Any

from .tool import Tool
from ..rag_client import RagClient


class RagRetrieveTool(Tool):
    """调用外部 RAG 检索接口并返回结构化结果。"""

    def __init__(self, workspace: Path, rag_client: RagClient):
        super().__init__(workspace)
        self.rag_client = rag_client

    @property
    def name(self) -> str:
        return "rag_retrieve"

    @property
    def description(self) -> str:
        return "Retrieve knowledge chunks from RAG backend by query."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The user query used for retrieval."},
                "top_k": {"type": "integer", "description": "Max number of chunks to return.", "default": 4},
                # "filters": {"type": "object", "description": "Optional retrieval filters."},
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        top_k: int = 4,
        session_id: str = "default",
        filters: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        result = await self.rag_client.retrieve(
            query=query,
            top_k=top_k,
            session_id=session_id,
            filters=filters or {},
        )
        return json.dumps(result, ensure_ascii=False)