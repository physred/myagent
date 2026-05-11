# main.py
import asyncio
import os
from datetime import datetime
from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from agent.loop import AgentLoop
from agent.hook import (
    EVENT_AFTER_MODEL_CALL,
    EVENT_AFTER_RETRIEVAL,
    EVENT_AFTER_TOOL_EXECUTE,
    EVENT_BEFORE_MODEL_CALL,
    EVENT_BEFORE_RETRIEVAL,
    EVENT_BEFORE_TOOL_EXECUTE,
    EVENT_REQUEST_END,
    EVENT_REQUEST_START,
)

from dotenv import load_dotenv
load_dotenv("/data/hdd3/agent/myagent/.env")

async def run_agent(user_input: str, session_id: str = "default") -> str:
    agent = AgentLoop()

    async def on_chunk(event: dict):
        etype = event.get("type")
        if etype == "token":
            print(event["data"], end="", flush=True)
        elif etype == "step":
            print(f"\n[{event['data']}]", flush=True)
        elif etype == "tool":
            data = event["data"]
            if data.get("status") == "executing":
                print(f"\n[调用工具: {data['name']}]", flush=True)

    result = await agent.run(user_input, session_id, stream=True, on_chunk=on_chunk)
    return result

if __name__ == "__main__":
    session_id = "reAct_test"
    agent = AgentLoop(
        workspace=os.getenv("AGENT_WORKSPACE", "/data/hdd3/agent/myagent/workspace"),
    )
    if os.getenv("ENABLE_HOOK_LOG", "0") == "1":
        log_path = os.path.join(str(agent.workspace), "hook.log")

        def _log_event(payload: dict, label: str) -> None:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{ts}] {label}: {payload}\n"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)

        agent.hooks.on(EVENT_REQUEST_START, lambda p: _log_event(p, "request_start"))
        agent.hooks.on(EVENT_BEFORE_RETRIEVAL, lambda p: _log_event(p, "before_retrieval"))
        agent.hooks.on(EVENT_AFTER_RETRIEVAL, lambda p: _log_event(p, "after_retrieval"))
        agent.hooks.on(EVENT_BEFORE_MODEL_CALL, lambda p: _log_event(p, "before_model_call"))
        agent.hooks.on(EVENT_AFTER_MODEL_CALL, lambda p: _log_event(p, "after_model_call"))
        agent.hooks.on(EVENT_BEFORE_TOOL_EXECUTE, lambda p: _log_event(p, "before_tool_execute"))
        agent.hooks.on(EVENT_AFTER_TOOL_EXECUTE, lambda p: _log_event(p, "after_tool_execute"))
        agent.hooks.on(EVENT_REQUEST_END, lambda p: _log_event(p, "request_end"))
    print("欢迎使用myagent，输入 exit 或 quit 退出。")

    async def _cli_loop():
        async def on_chunk(event: dict):
            etype = event.get("type")
            if etype == "token":
                print(event["data"], end="", flush=True)
            elif etype == "step":
                print(f"[{event['data']}]", flush=True)
            elif etype == "tool":
                data = event["data"]
                if data.get("status") == "executing":
                    print(f"\n[调用工具: {data['name']}]", flush=True)

        while True:
            try:
                user_input = input("输入：").strip()
                if user_input.lower() in {"exit", "quit", "q"}:
                    print("再见！")
                    break
                if not user_input:
                    continue
                print("Agent：\n", end="", flush=True)
                await agent.run(
                    user_input,
                    session_id=session_id,
                    stream=True,
                    on_chunk=on_chunk,
                )
                print()  # 换行
            except (KeyboardInterrupt, EOFError):
                print("\n再见！")
                break

    asyncio.run(_cli_loop())