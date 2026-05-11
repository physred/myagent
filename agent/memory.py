from pathlib import Path
from typing import Optional
import json
from datetime import datetime


class MemoryManager:
    # 管理长期/持久化记忆（MEMORY.md）以及用于存放归档条目的 history.jsonl
    # 提供加载、保存、追加等简单接口，供 Consolidator 使用。

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_file = self.workspace / "MEMORY.md"
        self.workspace.mkdir(parents=True, exist_ok=True)
        if not self.memory_file.exists():
            self.memory_file.write_text(
                "# Long-term Memory\n\nThis file stores important facts and preferences that the agent should remember over time.\n",
                encoding="utf-8",
            )

    def load_memory(self) -> str:
        """读取 MEMORY.md 并返回文本内容（长期记忆）。"""
        try:
            return self.memory_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except Exception as e:
            return f"Error loading memory: {e}"

    def save_memory(self, content: str) -> None:
        """覆盖写入 MEMORY.md，用于将分析/归纳后的记忆固化到文件。"""
        self.memory_file.write_text(content, encoding="utf-8")

    def append_memory(self, note: str) -> None:
        """追加一条记忆笔记到 MEMORY.md。"""
        with self.memory_file.open("a", encoding="utf-8") as f:
            f.write("\n" + note)

    def get_memory_path(self) -> Path:
        # 返回 MEMORY.md 路径，供外部工具读取/编辑
        return self.memory_file

    def memory_exists(self) -> bool:
        return self.memory_file.exists()

    # -- history.jsonl support -------------------------------------------------
    def _history_file(self) -> Path:
        hist = self.workspace / "history.jsonl"
        # ensure directory
        hist.parent.mkdir(parents=True, exist_ok=True)
        return hist

    def append_history(self, entry: str) -> int:
        """Append an entry to history.jsonl and return auto-incrementing cursor."""
        hist = self._history_file()
        # determine next cursor
        cursor = 1
        try:
            if hist.exists():
                with hist.open("r", encoding="utf-8") as f:
                    lines = [l for l in f.read().splitlines() if l.strip()]
                    if lines:
                        try:
                            last = json.loads(lines[-1])
                            cursor = int(last.get("cursor", 0)) + 1
                        except Exception:
                            cursor = len(lines) + 1
        except Exception:
            cursor = 1

        record = {
            "cursor": cursor,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "content": entry,
        }
        try:
            with hist.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return cursor

    def raw_archive(self, messages: list[dict]) -> None:
        """回退归档：将原始消息按时间/角色格式化后写入 history.jsonl，
        用于摘要失败时保留会话内容。"""
        formatted = []
        for m in messages:
            ts = m.get("timestamp", "?")
            role = m.get("role", "?")
            content = m.get("content", "")
            formatted.append(f"[{ts[:16]}] {role.upper()}: {content}")
        entry = "[RAW] " + "\n".join(formatted)
        self.append_history(entry)


# ---------------------------------------------------------------------------
# Consolidator — lightweight consolidation for myagent
# ---------------------------------------------------------------------------


class Consolidator:
    # 轻量级合并器：当会话上下文超过预算时，将较早的消息归档到 history.jsonl。
    # 特点：基于字符数估算 token、按 user-turn 优先切分、更新 session.last_consolidated。

    SAFETY_BUFFER = 256

    def __init__(self, memory: MemoryManager, provider=None, context_window_tokens: int = 8192, max_completion_tokens: int = 1024):
        """初始化 Consolidator。

        参数:
        - memory: MemoryManager 实例
        - provider: 可选的模型提供者，必须实现 `call_model(messages, enable_thinking=False)` 异步方法
        - context_window_tokens / max_completion_tokens: 预算参数
        """
        self.memory = memory
        self.provider = provider
        self.context_window_tokens = context_window_tokens
        self.max_completion_tokens = max_completion_tokens

        self.last_consolidated = 0  # 游标：已归档消息的索引边界，初始为 0

    @staticmethod
    def estimate_message_tokens(message: dict) -> int:
        """估算单条消息的 token 数，针对中文/混合文本做简单优化：

        - 对 CJK（中文、日文、韩文）字符按 1 字符 ≈ 1 token 估算；
        - 对其他字符（拉丁字母、数字、标点等）按 3 字符 ≈ 1 token 估算；
        - 混合文本分别计算后求和，至少返回 1。
        """
        content = str(message.get("content") or "")
        # 延迟导入正则以避免模块级开销
        import re

        # 匹配 CJK 字符范围（常见汉字、扩展区和兼容区）
        cjk_pattern = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF]")
        cjk_chars = cjk_pattern.findall(content)
        cjk_count = len(cjk_chars)

        # 其余字符（去掉 CJK 及空白）
        others = cjk_pattern.sub("", content)
        others = re.sub(r"\s+", "", others)
        other_count = len(others)

        # 估算：CJK 每字符计 1 token，其他字符按 3 字符计 1 token
        other_tokens = other_count // 3
        tokens = cjk_count + other_tokens
        return max(1, tokens)

    def estimate_session_tokens(self, session) -> int:
        """估算会话中未归档部分的总 token 数。"""
        # 仅统计未归档（active）消息
        active = session.messages[session.last_consolidated :]
        total = sum(self.estimate_message_tokens(m) for m in active)
        return total

    def pick_boundary(self, session, tokens_to_remove: int) -> int | None:
        """选择合适的切分边界（返回新的 last_consolidated 索引或 None）。

        遍历未归档消息累加估算 token，优先在 user 消息边界进行切分，
        使得被移除的 token 数量满足要求。
        """
        start = session.last_consolidated
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None
        removed = 0
        for idx in range(start, len(session.messages)):
            msg = session.messages[idx]
            removed += self.estimate_message_tokens(msg)
            # 优先在用户消息边界切分以保持上下文连贯
            if msg.get("role") == "user" and removed >= tokens_to_remove:
                return idx + 1
        return None

    async def archive(self, messages: list[dict]) -> bool:
        """使用模型对选中的消息生成摘要并追加到 history.jsonl。

        若未配置 provider，则回退为轻量拼接摘要；若模型调用失败则降级为原始归档。
        返回 True 表示已归档（或降级归档成功），False 表示无操作。
        """
        if not messages:
            return False

        # 将消息格式化为可读的对话块
        formatted_lines = []
        for m in messages:
            ts = m.get("timestamp", "?")
            role = m.get("role", "?")
            content = m.get("content", "")
            # 保证每行不超长
            formatted_lines.append(f"[{ts[:16]}] {role.upper()}: {content}")
        formatted_text = "\n".join(formatted_lines)

        # 如果没有 provider，则使用本地轻量摘要（HEAD/TAIL）
        if not self.provider:
            head = "\n".join(formatted_lines[:5])
            tail = "\n".join(formatted_lines[-3:])
            summary = f"[AUTO-ARCHIVE] {len(messages)} messages\n\nHEAD:\n{head}\n\nTAIL:\n{tail}"
            try:
                self.memory.append_history(summary)
                return True
            except Exception:
                self.memory.raw_archive(messages)
                return True

        # 使用 provider 调用模型进行摘要
        try:
            system_prompt = (
                "请将下面的对话历史进行简洁总结，保留关键事实、结论和需要长期记忆的要点，" \
                "以中文或对话语言输出，字数控制在 300 字以内。"
            )
            messages_payload = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": formatted_text},
            ]
            resp = await self.provider.call_model(messages_payload, enable_thinking=False)
            # 尝试从响应中提取文本内容（兼容 dict/object 格式）
            summary = None
            try:
                choice = resp.choices[0]
                msg = getattr(choice, "message", None)
                if isinstance(msg, dict):
                    summary = msg.get("content")
                else:
                    summary = getattr(msg, "content", None) or getattr(choice, "text", None)
            except Exception:
                # 备用解析：部分 SDK 直接返回 text
                summary = getattr(resp, "text", None)

            if not summary:
                # 回退到简单拼接
                head = "\n".join(formatted_lines[:5])
                tail = "\n".join(formatted_lines[-3:])
                summary = f"[AUTO-ARCHIVE] {len(messages)} messages\n\nHEAD:\n{head}\n\nTAIL:\n{tail}"

            self.memory.append_history(summary)
            return True
        except Exception:
            # 在任何异常下降级为原始归档，确保消息不会丢失
            self.memory.raw_archive(messages)
            return True

    async def maybe_consolidate_by_tokens(self, session) -> None:
        """主入口：当未归档消息估算 token 超过预算时，触发归档流程。

        计算安全预算（context_window - completion_tokens - safety_buffer），
        若估算值超过预算则选择边界归档一段老消息，归档成功后前移
        `session.last_consolidated` 游标（调用方负责持久化 session）。
        """
        # 计算安全预算
        budget = self.context_window_tokens - self.max_completion_tokens - self.SAFETY_BUFFER
        if budget <= 0:
            return
        estimated = self.estimate_session_tokens(session)
        if estimated <= budget:
            return
        # 设定目标（预算的一半）以避免频繁来回归档
        target = budget // 2
        tokens_to_remove = max(1, estimated - target)
        boundary = self.pick_boundary(session, tokens_to_remove)
        if boundary is None:
            return
        chunk = session.messages[session.last_consolidated : boundary]
        if not chunk:
            return
        if await self.archive(chunk):
            session.last_consolidated = boundary
            # 调用方应在必要时保存 session
        return
