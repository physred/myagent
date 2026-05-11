from typing import Any

from .tool.tool import ToolRegistry
from .memory import MemoryManager
from .skill import SkillManager


class ContextBuilder:
    """构建对话上下文和消息历史"""

    def __init__(self, registry: ToolRegistry, memory_manager: MemoryManager | None = None, skill_manager: SkillManager | None = None):
        self.registry = registry
        self.memory_manager = memory_manager
        self.skill_manager = skill_manager

    def build_system_message(self) -> dict[str, str]:
        """构建系统消息，包含工具描述和使用说明"""
        skills_text = self._format_skills_for_prompt()
        tools_text = self._format_tools_for_prompt()
        memory_text = self._format_memory_for_prompt()
        return {
            "role": "system",
            "content": (
                "You are an intelligent assistant with access to a knowledge base (RAG) and file tools.\n\n"
                "## How to answer questions about documents\n"
                "When the user asks about uploaded documents or their content, the knowledge base retrieval "
                "results are already provided in the conversation context. Use them directly — do NOT search "
                "the workspace for PDF or document files. The documents are NOT stored in the workspace.\n\n"
                "## Guidelines\n"
                "- For questions about uploaded documents: use the knowledge retrieval evidence provided in context.\n"
                "- For general questions, greetings: answer directly from your knowledge.\n"
                "- If retrieval evidence is provided, base your answer on it and cite sources.\n"
                "- If no evidence is found, say so honestly rather than searching files.\n"
                "- File tools (read_file, list_dir, etc.) are for workspace files, NOT for user-uploaded documents.\n\n"
                "If the user shares personal preferences, use the remember tool to store them.\n\n"
                f"{memory_text}"
                f"Available tools:\n{tools_text}\n\n"
                "## Tool Calling Rules (CRITICAL)\n"
                "When you need to use a tool, you MUST output a JSON object in EXACTLY this format — "
                "no other format will work:\n"
                '\n{"tool_call": {"name": "tool_name", "arguments": {"param": "value"}}}\n\n'
                "IMPORTANT:\n"
                "- Do NOT ask for confirmation before calling a tool. Just call it.\n"
                "- Output the JSON directly. The system will parse it and execute the tool automatically.\n"
                "- You may add text BEFORE or AFTER the JSON, but the JSON itself must be present.\n"
                "- If a user request requires a tool and you do not output the JSON, the tool will NOT be executed.\n\n"
                "## ReAct Reasoning Mode\n"
                "For complex tasks requiring multiple steps, think step by step using this pattern:\n\n"
                "1. Before each tool call, briefly explain your reasoning in Chinese (思考: ...)\n"
                "2. Then IMMEDIATELY output the tool_call JSON on the same response\n"
                "3. After receiving the tool result (Observation), analyze it and decide next step\n"
                "4. Repeat until you have fully completed the user's request\n\n"
                "CRITICAL RULE: Every response must contain EITHER a tool_call JSON OR a final answer. "
                "NEVER output only thinking text without one of these two. "
                "If you are still reasoning and the task is not done, you MUST output a tool_call. "
                "If you have fully completed the task, output the final answer directly.\n\n"
                "Example (task NOT done → must call tool):\n"
                "思考: 用户要求总结文件内容，我需要先读取文件。\n"
                '{"tool_call": {"name": "read_file", "arguments": {"path": "test.txt"}}}\n\n'
                "Example (task done → final answer):\n"
                "思考: 所有步骤已完成，结果已写入文件。\n"
                "已成功将冒泡排序代码添加到 sort.py 中。文件现在包含 quick_sort 和 bubble_sort 两个函数。\n\n"
                f"Available skills:\n{skills_text}\n\n"
                "Skills describe higher-level tasks and are not themselves tools.\n"
                "Do not call skill names directly in tool_call. Only call registered tool names.\n\n"
            ),
        }

    def _format_memory_for_prompt(self) -> str:
        """将 memory 内容格式化为系统 prompt 的一部分"""
        if not self.memory_manager:
            return ""

        memory_content = self.memory_manager.load_memory().strip()
        if not memory_content:
            return ""

        return f"Long-term memory:\n{memory_content}\n\n"

    def _format_skills_for_prompt(self) -> str:
        """将 skill 定义格式化为系统 prompt 的一部分"""
        if not self.skill_manager:
            return ""

        return self.skill_manager.to_prompt()

    def _format_tools_for_prompt(self) -> str:
        """将工具定义格式化为文本描述"""
        lines = []
        for tool_def in self.registry.get_definitions():
            lines.append(f"- {tool_def['name']}: {tool_def['description']}")
            if 'parameters' in tool_def and 'properties' in tool_def['parameters']:
                props = tool_def['parameters']['properties']
                required = tool_def['parameters'].get('required', [])
                for param_name, param_info in props.items():
                    req_mark = " (required)" if param_name in required else ""
                    ptype = param_info.get("type", "")
                    desc = param_info.get('description', '')
                    lines.append(f"  - {param_name}{req_mark}: {desc} [{ptype}]")
        return "\n".join(lines)

    def build_initial_messages(self, user_input: str, prior_messages: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
        """构建初始对话消息列表，包括之前的会话历史"""
        messages: list[dict[str, str]] = [self.build_system_message()]
        if prior_messages:
            for prior in prior_messages:
                role = prior.get("role")
                content = prior.get("content", "")
                if role in {"user", "assistant"} and content:
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_input})
        return messages

    def add_assistant_message(self, messages: list[dict[str, str]], content: str) -> list[dict[str, str]]:
        """添加助手消息到对话历史"""
        messages = messages.copy()
        messages.append({"role": "assistant", "content": content})
        return messages

    def add_tool_result_message(self, messages: list[dict[str, str]], tool_name: str, result: str) -> list[dict[str, str]]:
        """添加工具执行结果消息到对话历史"""
        messages = messages.copy()
        messages.append({"role": "user", "content": f"Tool result for {tool_name}: {result}"})
        return messages

    def add_retrieval_context(self, messages: list[dict[str, str]], retrieval: dict[str, Any] | None) -> list[dict[str, str]]:
        """将 RAG 检索结果注入消息上下文。"""
        if not retrieval:
            return messages

        chunks = retrieval.get("chunks", [])
        trace_id = retrieval.get("trace_id", "")
        rag_answer = retrieval.get("answer", "")

        if not chunks and not rag_answer:
            content = (
                "Knowledge retrieval result: no relevant evidence found in the knowledge base. "
                "Tell the user that no relevant content was found in the uploaded documents. "
                "Do NOT search the workspace for documents."
            )
        else:
            lines: list[str] = ["Knowledge retrieval evidence from uploaded documents:"]
            if rag_answer:
                lines.append(f"\nRAG-generated answer: {rag_answer}\n")
            for idx, chunk in enumerate(chunks, start=1):
                source = chunk.get("source", "unknown")
                score = chunk.get("score", "")
                text = str(chunk.get("text", "")).strip()
                lines.append(f"[{idx}] source={source} score={score}")
                lines.append(text)
            if trace_id:
                lines.append(f"trace_id={trace_id}")
            lines.append("Base your answer on this evidence. Cite sources like [1], [2].")
            lines.append("Do NOT use file tools to search for documents — the evidence is already here.")
            content = "\n".join(lines)

        updated = messages.copy()
        updated.append({"role": "user", "content": content})
        return updated

    def clean_tool_call_from_content(self, content: str) -> str:
        """从助手回复内容中移除所有 tool_call JSON 对象（括号深度计数）。"""
        marker = '"tool_call"'
        result = content
        while True:
            idx = result.find(marker)
            if idx == -1:
                break
            brace_start = result.rfind("{", 0, idx)
            if brace_start == -1:
                break
            # 括号深度计数找到闭合 }
            depth = 0
            in_string = False
            escape = False
            end = -1
            for i in range(brace_start, len(result)):
                c = result[i]
                if escape:
                    escape = False
                    continue
                if c == '\\' and in_string:
                    escape = True
                    continue
                if c == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end == -1:
                break
            result = result[:brace_start] + result[end + 1:]
        return result.strip()