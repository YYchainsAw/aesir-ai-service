"""策划书 §5.1 第 4 层的 YAML 策略加载：阈值与优先级单一来源。

``data/policy/tactical_policy.yaml`` 是唯一配置源（试玩调参只改 YAML 不改代码）。
进程启动时加载一次，修改文件后重启服务生效；结构非法时快速失败——
策略文件是版本库资产而非运行时可变输入，与协议「先改文档再改代码」同一纪律。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_POLICY_PATH = Path(__file__).resolve().parents[3] / "data" / "policy" / "tactical_policy.yaml"


class TacticalPolicyError(RuntimeError):
    """策略 YAML 缺失或不符合配置契约。"""


@dataclass(frozen=True)
class Thresholds:
    player_hp_critical: float
    player_hp_low: float
    companion_mp_low: float
    boss_melee_range_m: float


@dataclass(frozen=True)
class Priorities:
    # /v1/tactical/resolve（玩家请求路径）
    major_heal: int
    quick_heal: int
    shield: int
    burst: int
    burst_pending_stun: int
    retreat: int
    follow: int
    # /v1/combat/events（事件策略路径）
    event_major_heal: int
    event_quick_heal: int
    event_shield: int
    event_burst: int


@dataclass(frozen=True)
class TacticalPolicy:
    revision: str
    event_revision: str
    thresholds: Thresholds
    priorities: Priorities


def _require(mapping: dict[str, Any], key: str, parent: str) -> Any:
    if key not in mapping:
        raise TacticalPolicyError(f"策略 YAML 缺少字段：{parent}.{key}")
    return mapping[key]


def _build(path: Path) -> TacticalPolicy:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TacticalPolicyError(f"策略文件不存在：{path}") from exc
    except yaml.YAMLError as exc:
        raise TacticalPolicyError(f"策略 YAML 解析失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise TacticalPolicyError("策略 YAML 顶层必须是映射")

    thresholds_raw = _require(raw, "thresholds", "顶层")
    priorities_raw = _require(raw, "priorities", "顶层")
    thresholds = Thresholds(
        player_hp_critical=float(_require(thresholds_raw, "player_hp_critical", "thresholds")),
        player_hp_low=float(_require(thresholds_raw, "player_hp_low", "thresholds")),
        companion_mp_low=float(_require(thresholds_raw, "companion_mp_low", "thresholds")),
        boss_melee_range_m=float(_require(thresholds_raw, "boss_melee_range_m", "thresholds")),
    )
    for name in ("player_hp_critical", "player_hp_low", "companion_mp_low"):
        value = getattr(thresholds, name)
        if not 0 <= value <= 100:
            raise TacticalPolicyError(f"thresholds.{name} 必须在 [0,100]，收到 {value}")
    if thresholds.player_hp_low < thresholds.player_hp_critical:
        raise TacticalPolicyError(
            "thresholds.player_hp_low 必须 >= player_hp_critical（低血阈值先于中血阈值触发）"
        )

    priority_names = (
        "major_heal", "quick_heal", "shield", "burst", "burst_pending_stun",
        "retreat", "follow", "event_major_heal", "event_quick_heal",
        "event_shield", "event_burst",
    )
    priorities = Priorities(
        **{name: int(_require(priorities_raw, name, "priorities")) for name in priority_names}
    )
    for name in priority_names:
        value = getattr(priorities, name)
        if not 0 <= value <= 100:
            raise TacticalPolicyError(f"priorities.{name} 必须在 [0,100]，收到 {value}")

    revision = str(_require(raw, "revision", "顶层"))
    event_revision = str(_require(raw, "event_revision", "顶层"))
    return TacticalPolicy(
        revision=revision,
        event_revision=event_revision,
        thresholds=thresholds,
        priorities=priorities,
    )


def load_tactical_policy(path: Path = _POLICY_PATH) -> TacticalPolicy:
    """读取并校验策略 YAML；不做缓存，调用方一般走 ``get_policy()``。"""
    return _build(path)


_cached: TacticalPolicy | None = None


def get_policy() -> TacticalPolicy:
    """进程内缓存的策略实例；测试需要重新加载时调用 ``reset_policy_cache()``。"""
    global _cached
    if _cached is None:
        _cached = load_tactical_policy()
    return _cached


def reset_policy_cache() -> None:
    """清空缓存（仅测试用）。"""
    global _cached
    _cached = None
