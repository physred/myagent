import json
import os
from typing import Any, Awaitable, Callable

from utiles.utiles import JsonBraceCounter, extract_balanced_json

from provider import ProviderManager

from .tool.tool import ToolRegistry
from .tool.filsesystem import ReadFileTool, WriteFileTool, ListDirTool, CreateTool
from .tool.remember import RememberTool
from .tool.rag_retrieve import RagRetrieveTool
from .content import ContextBuilder
from .memory import MemoryManager, Consolidator
from .session import SessionManager
from .skill import SkillManager
from .rag_client import RagClient
from .hook import (
    HookBus,
    EVENT_AFTER_RETRIEVAL,
    EVENT_BEFORE_RETRIEVAL,
    EVENT_REQUEST_END,
    EVENT_REQUEST_START,
)

class AgentLoop:
    """Agent 主循环：负责接收输入、构建上下文、调用模型并执行工具。

    该类封装模型客户端、工具注册、会话管理与简单的合并器调用点。
    """
    def __init__(
        self,
        workspace: str | None = None,
    ):
        """初始化 AgentLoop。

        参数说明：
        - workspace: 工作目录，用于保存会话与记忆文件
        """
        # 初始化工作目录和会话管理器
        from pathlib import Path
        self.workspace = Path(workspace) if workspace else Path("/data/hdd3/agent") / "myagent" / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.root = Path(__file__).resolve().parent.parent
        self.skill_manager = SkillManager(self.root / "skill")

        self.hooks = HookBus()

        # 通过 ProviderManager 根据 PROVIDER_TYPE 环境变量创建对应提供者
        pm = ProviderManager(hooks=self.hooks)
        self.provider = pm.create()

        self.rag_client = RagClient()
        self.rag_top_k = int(os.getenv("RAG_TOP_K", "4"))

        self.memory_manager = MemoryManager(self.workspace)
        # simple consolidator: archive old messages when prompt grows too large
        
        self.registry = ToolRegistry(hooks=self.hooks)

        #文件读写工具
        self.registry.register(ReadFileTool(self.workspace))
        self.registry.register(WriteFileTool(self.workspace))
        self.registry.register(ListDirTool(self.workspace))
        self.registry.register(CreateTool(self.workspace))

        #记忆工具
        self.registry.register(RememberTool(self.workspace, self.memory_manager))
        self.registry.register(RagRetrieveTool(self.workspace, self.rag_client))

        self.session_manager = SessionManager(self.workspace)
        self.context_builder = ContextBuilder(self.registry, self.memory_manager, self.skill_manager)

        self.consolidator = Consolidator(
            memory=self.memory_manager,
            provider=self.provider,
            context_window_tokens=8192,
            max_completion_tokens=1024,
        )

    def build_messages(self, user_input: str, prior_messages: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
        """构建发送给模型的消息列表，包含用户输入与 prior_messages。

        仅为 ContextBuilder 的简单封装，返回 messages 列表。
        """
        return self.context_builder.build_initial_messages(user_input, prior_messages)

    def _extract_message(self, response: Any) -> dict[str, Any]:
        """从模型响应中提取消息字典（兼容不同响应格式）。"""
        choice = response.choices[0]
        msg = choice.message

        if isinstance(msg, dict):
            return msg
        return {
            "content": getattr(msg, "content", ""),
            "tool_calls": getattr(msg, "tool_calls", None),
        }


    @staticmethod
    def _try_parse_tool_json(text: str) -> dict | None:
        """尝试从文本中解析出包含 tool_call 的 JSON 对象。

        先尝试原样解析，若失败则逐步补全缺失的右花括号（最多补 5 层）。
        """
        for extra_braces in range(6):
            candidate = text + "}" * extra_braces
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and "tool_call" in data:
                    return data
            except json.JSONDecodeError:
                continue
        return None

    def _extract_tool_call(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """从 assistant 内容中解析嵌入的工具调用 JSON 并返回工具调用列表。

        通过括号深度计数提取完整 JSON。若 LLM 输出的 JSON 缺少闭合括号，
        则尝试从 marker 位置截取到文本末尾并自动补全。
        """
        content = message.get("content", "").strip()
        if not content:
            return []

        tool_calls = []
        search_from = 0
        marker = '"tool_call"'

        while True:
            idx = content.find(marker, search_from)
            if idx == -1:
                break
            brace_start = content.rfind("{", 0, idx)
            if brace_start == -1:
                search_from = idx + len(marker)
                continue

            # 策略1: 括号平衡提取
            json_str = extract_balanced_json(content, brace_start)
            if json_str:
                try:
                    data = json.loads(json_str)
                    tool_call = data.get("tool_call")
                    if isinstance(tool_call, dict) and "name" in tool_call:
                        tool_calls.append(tool_call)
                        search_from = brace_start + len(json_str)
                        continue
                except json.JSONDecodeError:
                    pass

            # 策略2: 从 brace_start 截到末尾，尝试补全缺失的 }
            remaining = content[brace_start:]
            data = self._try_parse_tool_json(remaining)
            if data:
                tool_call = data.get("tool_call")
                if isinstance(tool_call, dict) and "name" in tool_call:
                    tool_calls.append(tool_call)
                    search_from = len(content)
                    continue

            search_from = idx + len(marker)

        return tool_calls

    async def _execute_tool_call(self, tool_call: dict[str, Any]) -> str:
        """执行一个工具调用并返回结果文本。

        工具通过 `ToolRegistry` 调度执行，arguments 从工具调用中提取。
        """
        arguments = tool_call.get("arguments", {})
        return await self.registry.execute(tool_call["name"], arguments)

    async def _emit_chunk(
        self,
        on_chunk: Callable[[dict], Awaitable[None]] | None,
        event: dict,
    ) -> None:
        if on_chunk:
            try:
                await on_chunk(event)
            except Exception:
                pass

    async def run(
        self,
        user_input: str,
        session_id: str = "default",
        kb_id: str | None = None,
        stream: bool = False,
        on_chunk: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """主运行方法：处理一次用户输入并返回结构化结果。

        参数:
        - stream: 为 True 时使用 call_model_stream 逐 token 输出
        - on_chunk: 流式事件回调，接收 {"type": "token/step/tool/done", "data": ...}

        返回 dict 包含:
        - answer: 最终回答文本
        - reasoning: 中间推理步骤描述
        - tools: 工具调用记录 [{name, input, output}]
        - sources: RAG 检索来源 [{chunk_id, source, score, text}]
        """
        reasoning_steps = []
        tools_used = []
        sources = []

        await self.hooks.emit(
            EVENT_REQUEST_START,
            {"session_id": session_id, "user_input": user_input},
        )

        # ——获取或创建会话——
        session = self.session_manager.get_or_create_session(session_id)
        try:
            await self.consolidator.maybe_consolidate_by_tokens(session)
            self.session_manager.save_session(session)
        except Exception:
            pass

        prior_session_messages = session.get_history()

        # —— 组织初始输入 ——
        messages = self.context_builder.build_initial_messages(user_input, prior_session_messages)

        # ── RAG 检索 ──
        await self._emit_chunk(on_chunk, {"type": "step", "data": "RAG 检索中..."})
        await self.hooks.emit(
            EVENT_BEFORE_RETRIEVAL,
            {"session_id": session_id, "query": user_input, "top_k": self.rag_top_k},
        )
        try:
            retrieval_result = await self.rag_client.retrieve(
                query=user_input,
                top_k=self.rag_top_k,
                kb_id=kb_id,
            )
            sources = retrieval_result.get("chunks", [])
            err = retrieval_result.get("error", "")
            if err:
                reasoning_steps.append(f"1) RAG 检索: 错误 — {err}")
            else:
                reasoning_steps.append(f"1) RAG 检索: 从知识库检索到 {len(sources)} 条相关内容")
            await self.hooks.emit(
                EVENT_AFTER_RETRIEVAL,
                {"session_id": session_id, "result": retrieval_result},
            )
        except Exception as exc:
            reasoning_steps.append("1) RAG 检索: 未配置或检索失败")
            await self.hooks.emit(
                EVENT_AFTER_RETRIEVAL,
                {"session_id": session_id, "error": str(exc)},
            )
        messages = self.context_builder.add_retrieval_context(messages, retrieval_result)
        session.add_message("user", user_input)
        await self._emit_chunk(on_chunk, {
            "type": "retrieval_done",
            "data": {"source_count": len(sources)},
        })

        # ── Agent Loop (ReAct) ──
        max_iterations = 10
        step = 2
        for iteration in range(max_iterations):
            if stream:
                full_text = ""
                buffer = ""
                in_tool_json = False
                brace_counter = JsonBraceCounter()

                _TOOL_PREFIX = '{"tool_call"'

                async for token in self.provider.call_model_stream(messages, enable_thinking=False):
                    full_text += token

                    if not in_tool_json:
                        buffer += token
                        # 检查缓冲区是否包含完整 tool_call marker
                        if '"tool_call"' in buffer:
                            in_tool_json = True
                            brace_counter.reset()
                            brace_counter.feed(buffer)
                        else:
                            # 找 buffer 中最后一个 '{'，它可能是 tool_call JSON 的开头
                            last_brace = buffer.rfind("{")
                            if last_brace >= 0 and _TOOL_PREFIX.startswith(buffer[last_brace:].lstrip()):
                                # '{' 之后的内容还可能是 tool_call 前缀，只 flush 之前的安全部分
                                if last_brace > 0:
                                    await self._emit_chunk(on_chunk, {"type": "token", "data": buffer[:last_brace]})
                                    buffer = buffer[last_brace:]
                            elif buffer and not _TOOL_PREFIX.startswith(buffer.lstrip()):
                                # 整个 buffer 已不可能匹配，全部 flush
                                await self._emit_chunk(on_chunk, {"type": "token", "data": buffer})
                                buffer = ""
                            elif len(buffer) > 30:
                                # 限长保护：太长还不匹配则 flush
                                await self._emit_chunk(on_chunk, {"type": "token", "data": buffer})
                                buffer = ""
                    else:
                        buffer += token
                        brace_counter.feed(token)
                        if brace_counter.depth <= 0:
                            # JSON 闭合，抑制输出，工具信息由执行阶段 emit
                            buffer = ""
                            in_tool_json = False

                # flush 残余缓冲区
                if buffer and not in_tool_json:
                    await self._emit_chunk(on_chunk, {"type": "token", "data": buffer})

                message = {"content": full_text}
            else:
                response = await self.provider.call_model(messages, enable_thinking=False)
                message = self._extract_message(response)

            tool_calls = self._extract_tool_call(message)

            if not tool_calls:
                final_response = message.get("content", "")
                reasoning_steps.append(f"{step}) 生成最终回答")

                session.add_message("assistant", final_response)
                self.session_manager.save_session(session)

                await self.hooks.emit(
                    EVENT_REQUEST_END,
                    {"session_id": session_id, "response": final_response},
                )
                await self._emit_chunk(on_chunk, {"type": "done"})
                return {
                    "answer": final_response,
                    "reasoning": "\n".join(reasoning_steps),
                    "tools": tools_used,
                    "sources": sources,
                }

            # Execute all tool calls
            results = []
            for tool_call in tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("arguments", {})
                await self._emit_chunk(on_chunk, {
                    "type": "tool",
                    "data": {"name": tool_name, "status": "executing"},
                })
                result = await self._execute_tool_call(tool_call)
                results.append(f"{tool_name}: {result}")
                tools_used.append({
                    "name": tool_name,
                    "input": json.dumps(tool_args, ensure_ascii=False) if isinstance(tool_args, dict) else str(tool_args),
                    "output": result[:500],
                })
                reasoning_steps.append(f"{step}) 调用工具 {tool_name}")
                await self._emit_chunk(on_chunk, {
                    "type": "tool",
                    "data": {"name": tool_name, "status": "done", "output": result[:500]},
                })
                step += 1

            combined_result = "\n".join(results)

            assistant_content = self.context_builder.clean_tool_call_from_content(message.get("content", ""))
            messages = self.context_builder.add_assistant_message(messages, assistant_content)
            messages = self.context_builder.add_tool_result_message(messages, "multiple_tools", f"Observation:\n{combined_result}")

        # 达到迭代上限，强制要求模型给出最终回答
        messages.append({"role": "user", "content": "已达到最大推理步数限制，请基于已有信息直接给出最终回答，不要再调用工具。"})
        if stream:
            full_text = ""
            async for token in self.provider.call_model_stream(messages, enable_thinking=False):
                full_text += token
                await self._emit_chunk(on_chunk, {"type": "token", "data": token})
            final_response = full_text
        else:
            response = await self.provider.call_model(messages, enable_thinking=False)
            final_response = self._extract_message(response).get("content", "")

        reasoning_steps.append(f"{step}) 达到迭代上限，强制生成回答")
        session.add_message("assistant", final_response)
        self.session_manager.save_session(session)
        await self.hooks.emit(EVENT_REQUEST_END, {"session_id": session_id, "response": final_response})
        await self._emit_chunk(on_chunk, {"type": "done"})
        return {
            "answer": final_response,
            "reasoning": "\n".join(reasoning_steps),
            "tools": tools_used,
            "sources": sources,
        }
