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
    """一轮已完成的多模对话：玩家输入 + 艾莉回复文本 + 该轮情绪。

    ``emotion_id`` 是**情绪惯性的载体**（2026-09-21 实测复盘）：此前每轮独立
    生成、prompt 里没有「她现在什么心情」，模型只能按剧情张力重挑一个，于是
    出现无来由的情绪跳变与回摆。记下上一轮的情绪，下一轮作为当前心情注入，
    她才有「心情」可言。旧调用方不传时为空串，行为不变。
    """

    user_text: str
    reply_text: str
    emotion_id: str = ""


class SessionMemoryStore:
    """线程安全的会话记忆存储；max_turns 为 0 时等价于关闭记忆。

    键为 ``(companion_id, session_id)``（SDD T011 / FR-044 状态隔离）：
    不同角色的会话互不可见。``companion_id`` 缺省为 ``None``，兼容既有
    单角色调用方（companion chat 链路），行为不变。
    """

    def __init__(self, max_turns: int) -> None:
        self._max_turns = max(0, max_turns)
        self._lock = threading.Lock()
        self._sessions: dict[tuple[str | None, str], deque[DialogueTurn]] = {}

    @property
    def max_turns(self) -> int:
        return self._max_turns

    def history(
        self, session_id: str, companion_id: str | None = None
    ) -> tuple[DialogueTurn, ...]:
        """该角色该会话最近 N 轮（时间正序），无记忆时为空组。"""
        with self._lock:
            return tuple(self._sessions.get((companion_id, session_id), ()))

    def record(
        self,
        session_id: str,
        user_text: str,
        reply_text: str,
        companion_id: str | None = None,
        emotion_id: str = "",
    ) -> None:
        """记录一轮对话；超出窗口自动淘汰最旧一轮。

        ``emotion_id`` 为该轮回复的情绪（情绪惯性载体）；不传时为空串，
        调用方按「无心情可延续」处理，旧调用方行为不变。
        """
        if self._max_turns == 0:
            return
        with self._lock:
            turns = self._sessions.setdefault(
                (companion_id, session_id), deque(maxlen=self._max_turns)
            )
            turns.append(
                DialogueTurn(
                    user_text=user_text, reply_text=reply_text, emotion_id=emotion_id
                )
            )

    def clear(self, companion_id: str | None = None) -> int:
        """清空指定角色的全部会话记忆（console 记忆重置入口，SDD T015/T029）。

        返回被清除的会话数。``companion_id=None`` 时清空未分区（旧链路）会话。
        """
        with self._lock:
            keys = [key for key in self._sessions if key[0] == companion_id]
            for key in keys:
                del self._sessions[key]
            return len(keys)


# 进程级单例：会话记忆属于服务运行时状态，不随请求重建。
_store = SessionMemoryStore(max_turns=0)


def get_session_memory(max_turns: int) -> SessionMemoryStore:
    """按配置的窗口大小返回（并惰性初始化）进程级存储。"""
    global _store
    if _store.max_turns != max(0, max_turns):
        _store = SessionMemoryStore(max_turns)
    return _store
