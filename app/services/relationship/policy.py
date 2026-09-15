"""关系策略表加载（SDD T038 / 章程原则 I）。

阶段划分、事件增减幅度全部来自 ``data/policy/relationship_policy.yaml``，
代码不硬编码业务数值。进程启动时加载快照——改 YAML 后重启生效
（与 tactical_policy 同思路）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

_POLICY_PATH = Path("data/policy/relationship_policy.yaml")


@dataclass(frozen=True)
class StagePolicy:
    """单个关系阶段的行为参数（FR-016：每阶段须有可观察差异）。"""

    name: str
    low: int              # 数值区间下界（含）
    high: int             # 数值区间上界（含）
    address: str          # 阶段化称呼
    autonomy: str         # 主动度
    resource_willingness: str  # 资源投入意愿
    obedience: str        # 服从度（low=有权质疑危险指令）


@dataclass(frozen=True)
class RelationshipPolicy:
    revision: str
    min: int
    max: int
    initial: int
    stages: tuple[StagePolicy, ...]
    events: dict[str, int]  # 事件类型 → 数值增减；未登记事件一律忽略


_lock = threading.Lock()
_cached: RelationshipPolicy | None = None


def load_policy(path: Path = _POLICY_PATH) -> RelationshipPolicy:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    stages = tuple(
        StagePolicy(
            name=s["name"],
            low=s["range"][0],
            high=s["range"][1],
            address=s["address"],
            autonomy=s["autonomy"],
            resource_willingness=s["resource_willingness"],
            obedience=s["obedience"],
        )
        for s in data["stages"]
    )
    return RelationshipPolicy(
        revision=data["revision"],
        min=data["bounds"]["min"],
        max=data["bounds"]["max"],
        initial=data["bounds"]["initial"],
        stages=stages,
        events={name: int(spec["delta"]) for name, spec in data["events"].items()},
    )


def get_policy() -> RelationshipPolicy:
    global _cached
    with _lock:
        if _cached is None:
            _cached = load_policy()
        return _cached


def reset_policy_cache() -> None:
    """清空缓存（仅测试用）。"""
    global _cached
    with _lock:
        _cached = None
