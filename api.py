from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from agent.loop import AgentLoop

app = FastAPI(title="myagent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_agent: AgentLoop | None = None


class ChatRequest(BaseModel):
    query: str
    session_id: str | None = "default"
    kb_id: str | None = None
    stream: bool = False


class ToolCallRecord(BaseModel):
    name: str
    input: str
    output: str


class SourceRecord(BaseModel):
    chunk_id: str = ""
    source: str = ""
    score: float | None = None
    text: str = ""


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    reasoning: str = ""
    tools: list[ToolCallRecord] = []
    sources: list[SourceRecord] = []


def _get_agent() -> AgentLoop:
    global _agent
    if _agent is None:
        _agent = AgentLoop(
            workspace=os.getenv("AGENT_WORKSPACE", "/data/hdd3/agent/myagent/workspace"),
        )
    return _agent


@app.get("/", response_class=HTMLResponse)
async def root():
    return "agent已启动"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    agent = _get_agent()
    try:
        result = await agent.run(
            query,
            session_id=req.session_id or "default",
            kb_id=req.kb_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(
        answer=result["answer"],
        session_id=req.session_id or "default",
        reasoning=result.get("reasoning", ""),
        tools=[ToolCallRecord(**t) for t in result.get("tools", [])],
        sources=[SourceRecord(**s) for s in result.get("sources", [])],
    )


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    agent = _get_agent()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_chunk(event: dict):
        await queue.put(event)

    async def run_agent():
        try:
            await agent.run(
                query,
                session_id=req.session_id or "default",
                kb_id=req.kb_id,
                stream=True,
                on_chunk=on_chunk,
            )
        except Exception as exc:
            await queue.put({"type": "error", "data": str(exc)})
        finally:
            await queue.put(None)

    asyncio.create_task(run_agent())

    async def event_generator():
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
