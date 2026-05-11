import asyncio
import json
import os
from urllib import error, request

os.environ.setdefault("RAG_API_URL", "http://localhost:8000/api/v1/query")

class RagClient:
    """RAG 后端客户端。

    - 未配置 RAG_API_URL 时，返回本地 mock 数据，保证 Demo 可跑。
    - 配置后，通过 HTTP POST 调用后端检索接口。
    """

    def __init__(
        self,
        api_url: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.api_url = api_url or os.getenv("RAG_API_URL", "").strip()
        self.timeout_seconds = timeout_seconds

    async def retrieve(
        self,
        query: str,
        top_k: int = 4,
        kb_id: str | None = None,
    ) -> dict:
        if not self.api_url:
            return self._mock_retrieve(query, top_k)

        payload = {
            "query": query,
            "top_k": top_k,
            "kb_id": kb_id,
            "search_mode": os.getenv("RAG_SEARCH_MODE", "hybrid").strip() or "hybrid",
            "max_context_tokens": _safe_int(os.getenv("RAG_MAX_CONTEXT_TOKENS")),
        }
        if not payload["kb_id"]:
            return {"chunks": [], "error": "missing_kb_id", "trace_id": ""}

        return await asyncio.to_thread(self._http_retrieve_sync, payload)

    def _http_retrieve_sync(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
        }

        req = request.Request(self.api_url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if not isinstance(data, dict):
                    return {"chunks": [], "error": "invalid_response_format", "trace_id": ""}

                if "chunks" in data:
                    data.setdefault("trace_id", "")
                    return data

                return _map_query_response(data)
        except error.HTTPError as e:
            return {"chunks": [], "error": f"http_error:{e.code}", "trace_id": ""}
        except Exception as e:
            return {"chunks": [], "error": f"request_failed:{e}", "trace_id": ""}

    def _mock_retrieve(self, query: str, top_k: int) -> dict:
        # 保证无后端时链路可跑；后续接真实后端时无需改主流程。
        base_chunks = [
            {
                "chunk_id": "mock-1",
                "source": "mock://product_faq.md",
                "score": 0.91,
                "text": f"与问题“{query}”相关的示例知识片段：系统支持通过 RAG 检索后再生成答案。",
            },
            {
                "chunk_id": "mock-2",
                "source": "mock://deploy_guide.md",
                "score": 0.83,
                "text": "当检索证据不足时，回答应明确说明信息不足，避免编造结论。",
            },
        ]
        return {
            "chunks": base_chunks[: max(1, top_k)],
            "trace_id": "mock-trace",
            "latency_ms": 1,
        }


def _safe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _map_query_response(data: dict) -> dict:
    sources = data.get("sources") or []
    chunks = []
    for idx, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            continue
        chunks.append(
            {
                "chunk_id": source.get("chunk_id") or source.get("id") or f"src-{idx}",
                "source": source.get("doc_filename") or source.get("type") or "document",
                "score": source.get("score"),
                "text": source.get("snippet") or "",
            }
        )

    return {
        "chunks": chunks,
        "trace_id": data.get("metadata", {}).get("trace_id", ""),
        "answer": data.get("answer", ""),
        "search_mode": data.get("search_mode"),
    }