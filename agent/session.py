import json
import os
from pathlib import Path
from typing import Any, Optional
from datetime import datetime


class Session:
    """表示一个对话会话。

    此类保存会话ID、消息列表以及创建/更新时间。新增字段 `last_consolidated`
    用于标记已归档（consolidated）的消息游标，方便将老消息移动到长期历史。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: list[dict[str, Any]] = []
        # cursor of messages that have been consolidated (archived)
        # messages with index < last_consolidated are considered archived
        self.last_consolidated: int = 0
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    def add_message(self, role: str, content: str) -> None:
        """添加一条消息到会话并更新更新时间。

        参数:
        - role: 消息角色（如 'user' / 'assistant' / 'tool'）
        - content: 消息文本内容
        """
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        self.updated_at = datetime.now().isoformat()

    def get_messages(self) -> list[dict[str, Any]]:
        """返回会话中所有消息的浅拷贝（包含已归档和未归档）。"""
        return self.messages.copy()

    def get_history(self, max_messages: int = 50) -> list[dict[str, Any]]:
        """获取最近的未归档历史消息（最多 `max_messages` 条）。

        只返回 `last_consolidated` 之后（未归档）的消息，供上下文构建使用。
        """
        # only return messages that are not yet consolidated (archived)
        active = self.messages[self.last_consolidated :]
        recent = active[-max_messages:] if len(active) > max_messages else active
        return [{"role": m["role"], "content": m["content"]} for m in recent]
    
    def to_dict(self) -> dict[str, Any]:
        """将会话序列化为字典，包含 `last_consolidated` 以保留归档状态。"""
        return {
            "session_id": self.session_id,
            "messages": self.messages,
            "last_consolidated": self.last_consolidated,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        """从字典反序列化为 `Session` 实例，恢复 `last_consolidated`。"""
        session = cls(data["session_id"])
        session.messages = data["messages"]
        session.last_consolidated = int(data.get("last_consolidated", 0) or 0)
        session.created_at = data.get("created_at", session.created_at)
        session.updated_at = data.get("updated_at", session.updated_at)
        return session


class SessionManager:
    """会话管理器：负责会话的创建、加载、保存和删除。

    会话以 JSON 文件保存在 workspace/sessions 目录中，支持内存缓存以加速访问。
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = workspace / "sessions"
        self.sessions_dir.mkdir(exist_ok=True)
        self._sessions: dict[str, Session] = {}

    def _get_session_file(self, session_id: str) -> Path:
        """返回会话对应的 JSON 文件路径。"""
        return self.sessions_dir / f"{session_id}.json"

    def create_session(self, session_id: Optional[str] = None) -> Session:
        """创建并返回新的 `Session`，若 session_id 为 None 则生成唯一 ID。"""
        if session_id is None:
            # 生成基于时间戳的会话ID
            session_id = f"session_{int(datetime.now().timestamp())}"

        if session_id in self._sessions:
            return self._sessions[session_id]

        session = Session(session_id)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """尝试从内存或磁盘加载会话，找不到时返回 None。"""
        if session_id in self._sessions:
            return self._sessions[session_id]

        # 尝试从文件加载
        session_file = self._get_session_file(session_id)
        if session_file.exists():
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                session = Session.from_dict(data)
                self._sessions[session_id] = session
                return session
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Failed to load session {session_id}: {e}")

        return None

    def get_or_create_session(self, session_id: str) -> Session:
        """获取会话；若不存在则创建并返回新会话。"""
        session = self.get_session(session_id)
        if session is None:
            session = self.create_session(session_id)
        return session

    def save_session(self, session: Session) -> None:
        """将会话序列化保存到磁盘（workspace/sessions/<id>.json）。"""
        session_file = self._get_session_file(session.session_id)
        try:
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"Warning: Failed to save session {session.session_id}: {e}")

    def list_sessions(self) -> list[str]:
        """列出当前已知的所有会话 ID（内存缓存 + sessions 目录中的文件）。"""
        sessions = set(self._sessions.keys())

        # 添加文件中的会话
        if self.sessions_dir.exists():
            for file_path in self.sessions_dir.glob("*.json"):
                session_id = file_path.stem
                sessions.add(session_id)

        return sorted(list(sessions))

    def delete_session(self, session_id: str) -> bool:
        """删除指定会话（从内存与磁盘同时删除），返回是否成功。"""
        # 从内存中移除
        if session_id in self._sessions:
            del self._sessions[session_id]

        # 删除文件
        session_file = self._get_session_file(session_id)
        if session_file.exists():
            try:
                session_file.unlink()
                return True
            except IOError as e:
                print(f"Warning: Failed to delete session file {session_id}: {e}")
                return False

        return False