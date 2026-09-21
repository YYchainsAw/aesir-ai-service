"""运行期「最近观测」状态（US7 / T077 调试台数据源）。

调试台需要回答「她现在处于什么场景、上次是什么情绪」——这些是客户端侧
事实，服务端只在处理请求时顺带记下最近一次观测，供 ``/v1/console/state``
查询。进程内字典 + 有界（与心跳限流同一做法）；重启即清空属可接受语义
（调试视图，非权威状态——权威场景在 UE 快照里，原则 III）。
"""

import threading
from dataclasses import dataclass

_MAX_TRACKED = 64


@dataclass
class RuntimeObservation:
    scene: str = ""          # 最近一次心跳/指令快照的活动场景
    emotion_id: str = ""     # 最近一次输出表现的表情 ID
    last_seen: str = ""      # 最近一次观测时间（ISO-8601 UTC）


_lock = threading.Lock()
_observations: dict[str, RuntimeObservation] = {}


def record_observation(companion_id: str, *, scene: str | None = None,
                       emotion_id: str | None = None, last_seen: str = "") -> None:
    """更新某角色的最近观测（只更新给出的字段）。"""
    with _lock:
        obs = _observations.get(companion_id) or RuntimeObservation()
        if scene is not None:
            obs.scene = scene
        if emotion_id is not None:
            obs.emotion_id = emotion_id
        if last_seen:
            obs.last_seen = last_seen
        _observations[companion_id] = obs
        if len(_observations) > _MAX_TRACKED:
            # 丢弃最早插入的条目（dict 保序）
            _observations.pop(next(iter(_observations)))


def get_observation(companion_id: str) -> RuntimeObservation:
    """读取最近观测（无记录返回空观测，不虚构）。"""
    with _lock:
        obs = _observations.get(companion_id)
        return obs or RuntimeObservation()


def reset_runtime_observations() -> None:
    """清空（仅测试用）。"""
    with _lock:
        _observations.clear()
