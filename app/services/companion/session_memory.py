"""非战斗对话的短期会话记忆（方案 B）。

按 ``session_id`` 维护最近 N 轮（用户输入 + 艾莉回复）的滚动窗口，注入 LLM
prompt 作为对话历史。进程内存、不持久化：服务重启即清空，刻意不做跨会话
玩家画像或长期记忆（见 primary_companion.yaml 的 runtime_state_policy）。
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class DialogueTurn:
    """一轮已完成的多模对话：玩家输入 + 艾莉回复文本。"""

    user_text: str
    reply_text: str


class SessionMemoryStore:
    """线程安全的会话记忆存储；max_turns 为 0 时等价于关闭记忆。"""

    def __init__(self, max_turns: int) -> None:
        self._max_turns = max(0, max_turns)
        self._lock = threading.Lock()
        self._sessions: dict[str, deque[DialogueTurn]] = {}

    @property
    def max_turns(self) -> int:
        return self._max_turns

    def history(self, session_id: str) -> tuple[DialogueTurn, ...]:
        """该会话最近 N 轮（时间正序），无记忆时为空组。"""
        with self._lock:
            return tuple(self._sessions.get(session_id, ()))

    def record(self, session_id: str, user_text: str, reply_text: str) -> None:
        """记录一轮对话；超出窗口自动淘汰最旧一轮。"""
        if self._max_turns == 0:
            return
        with self._lock:
            turns = self._sessions.setdefault(session_id, deque(maxlen=self._max_turns))
            turns.append(DialogueTurn(user_text=user_text, reply_text=reply_text))


# 进程级单例：会话记忆属于服务运行时状态，不随请求重建。
_store = SessionMemoryStore(max_turns=0)


def get_session_memory(max_turns: int) -> SessionMemoryStore:
    """按配置的窗口大小返回（并惰性初始化）进程级存储。"""
    global _store
    if _store.max_turns != max(0, max_turns):
        _store = SessionMemoryStore(max_turns)
    return _store
