"""行为目录与自主行为候选生成（SDD T051 / FR-020、FR-025、FR-040）。

``data/policy/agency_policy.yaml`` 是唯一配置源（章程原则 I）：行为白名单、
适用域、目标类型与距离约束、仲裁优先级、节流参数。加载与校验模式参照
``tactical/policy.py``（frozen dataclass + 快速失败 + 进程缓存）。

候选生成是**确定性规则驱动**（无 LLM，FR-028 不猜测）：依据世界快照
（时间、血量、可交互物、区域、玩家状态）从目录挑候选，并完成三重不可执行
防护——目标 ID 必须出现在快照中、类型必须在 ``allowed_kinds``、距离必须在
``max_distance_m`` 内。宁可返回空列表，也不虚构目标（FR-025/FR-040）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from app.schemas.world_context import Scene, WorldContext

_POLICY_PATH = Path(__file__).resolve().parents[3] / "data" / "policy" / "agency_policy.yaml"

_VALID_SCENES = frozenset({"combat", "exploration", "camp", "conversation", "idle"})
_VALID_KINDS = frozenset({"item", "npc", "prop", "poi"})


class AgencyPolicyError(RuntimeError):
    """策略 YAML 缺失或不符合配置契约。"""


@dataclass(frozen=True)
class BehaviorSpec:
    """目录中一个行为的全部参数约束。"""

    name: str
    domains: frozenset[str]
    priority: int
    allowed_kinds: frozenset[str] | None  # None = 无目标行为（如 rest/self_talk）
    max_distance_m: float
    description: str = ""  # 能力注册表（FR-035）登记本行为时的说明文案


@dataclass(frozen=True)
class ArbiterPolicy:
    priority_order: tuple[str, ...]


@dataclass(frozen=True)
class ThrottlePolicy:
    dedup_window_seconds: float
    max_per_window: int
    no_interrupt_when: tuple[str, ...]


@dataclass(frozen=True)
class DirectivePolicy:
    autonomy_expires_seconds: float
    combat_expires_seconds: float


@dataclass(frozen=True)
class AgencyPolicy:
    revision: str
    behaviors: Mapping[str, BehaviorSpec]
    arbiter: ArbiterPolicy
    throttle: ThrottlePolicy
    directives: DirectivePolicy


@dataclass(frozen=True)
class BehaviorCandidate:
    """自主行为候选：仲裁（T052）与节流（T053）的统一输入。"""

    behavior: str
    category: str          # arbiter 六级类目之一
    priority: int
    target_id: str | None  # 必须是快照中出现过的 ID（FR-040）
    trigger_source: str    # 触发条件代号（节流键维度：同目标不同原因不算重复）
    reason_codes: list[str] = field(default_factory=list)
    payload: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 策略加载与校验
# ---------------------------------------------------------------------------
def _require(mapping: dict[str, Any], key: str, parent: str) -> Any:
    if key not in mapping:
        raise AgencyPolicyError(f"策略 YAML 缺少字段：{parent}.{key}")
    return mapping[key]


def _build(path: Path) -> AgencyPolicy:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AgencyPolicyError(f"策略文件不存在：{path}") from exc
    except yaml.YAMLError as exc:
        raise AgencyPolicyError(f"策略 YAML 解析失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise AgencyPolicyError("策略 YAML 顶层必须是映射")

    revision = str(_require(raw, "revision", "顶层"))

    behaviors_raw = _require(raw, "behaviors", "顶层")
    if not isinstance(behaviors_raw, dict) or not behaviors_raw:
        raise AgencyPolicyError("behaviors 必须是非空映射")
    behaviors: dict[str, BehaviorSpec] = {}
    for name, spec_raw in behaviors_raw.items():
        if not isinstance(spec_raw, dict):
            raise AgencyPolicyError(f"behaviors.{name} 必须是映射")
        domains = frozenset(_require(spec_raw, "domains", f"behaviors.{name}"))
        unknown = domains - _VALID_SCENES
        if unknown:
            raise AgencyPolicyError(f"behaviors.{name}.domains 含未知场景：{sorted(unknown)}")
        priority = int(_require(spec_raw, "priority", f"behaviors.{name}"))
        if not 0 <= priority <= 100:
            raise AgencyPolicyError(f"behaviors.{name}.priority 必须在 [0,100]")
        kinds_raw = spec_raw.get("allowed_kinds", None)
        allowed_kinds = (
            None if kinds_raw is None else frozenset(kinds_raw)
        )
        if allowed_kinds is not None and allowed_kinds - _VALID_KINDS:
            raise AgencyPolicyError(
                f"behaviors.{name}.allowed_kinds 含未知类型：{sorted(allowed_kinds - _VALID_KINDS)}"
            )
        behaviors[str(name)] = BehaviorSpec(
            name=str(name),
            domains=domains,
            priority=priority,
            allowed_kinds=allowed_kinds,
            max_distance_m=float(spec_raw.get("max_distance_m", 0.0)),
            description=str(spec_raw.get("description", "")),
        )

    arbiter_raw = _require(raw, "arbiter", "顶层")
    priority_order = tuple(_require(arbiter_raw, "priority_order", "arbiter"))
    if len(priority_order) != len(set(priority_order)):
        raise AgencyPolicyError("arbiter.priority_order 存在重复类目")

    throttle_raw = _require(raw, "throttle", "顶层")
    throttle = ThrottlePolicy(
        dedup_window_seconds=float(_require(throttle_raw, "dedup_window_seconds", "throttle")),
        max_per_window=int(_require(throttle_raw, "max_per_window", "throttle")),
        no_interrupt_when=tuple(_require(throttle_raw, "no_interrupt_when", "throttle")),
    )
    if throttle.dedup_window_seconds < 0 or throttle.max_per_window < 1:
        raise AgencyPolicyError("throttle 参数必须为正")

    directives_raw = _require(raw, "directives", "顶层")
    directives = DirectivePolicy(
        autonomy_expires_seconds=float(_require(directives_raw, "autonomy_expires_seconds", "directives")),
        combat_expires_seconds=float(_require(directives_raw, "combat_expires_seconds", "directives")),
    )
    if directives.autonomy_expires_seconds <= 0 or directives.combat_expires_seconds <= 0:
        raise AgencyPolicyError("directives 有效期必须为正")

    return AgencyPolicy(
        revision=revision,
        behaviors=behaviors,
        arbiter=ArbiterPolicy(priority_order=priority_order),
        throttle=throttle,
        directives=directives,
    )


_cached: AgencyPolicy | None = None


def get_agency_policy() -> AgencyPolicy:
    """进程内缓存加载；修改 YAML 后重启服务生效（与 tactical/policy 同一纪律）。"""
    global _cached
    if _cached is None:
        _cached = _build(_POLICY_PATH)
    return _cached


def reset_agency_policy_cache() -> None:
    """清空缓存（测试用）。"""
    global _cached
    _cached = None


# ---------------------------------------------------------------------------
# 域过滤与候选生成
# ---------------------------------------------------------------------------
def behaviors_allowed(scene: Scene, policy: AgencyPolicy | None = None) -> list[BehaviorSpec]:
    """返回该场景允许的目录行为（combat 域无生活行为，FR-019）。"""
    if policy is None:
        policy = get_agency_policy()
    return [spec for spec in policy.behaviors.values() if scene in spec.domains]


def _target_ok(spec: BehaviorSpec, target) -> bool:
    """不可执行防护三重校验：ID 在快照 + 类型白名单 + 距离上限。"""
    if spec.allowed_kinds is None or target is None:
        return spec.allowed_kinds is None
    if target.kind not in spec.allowed_kinds:
        return False
    return target.distance_m <= spec.max_distance_m


def generate_candidates(
    ctx: WorldContext, *, relationship_stage: str = "", policy: AgencyPolicy | None = None
) -> list[BehaviorCandidate]:
    """基于世界快照生成自主行为候选（确定性规则，无 LLM）。

    战斗场景直接返回空（FR-019，战斗决策归 v0.1/v0.2 链路）。
    """
    if policy is None:
        policy = get_agency_policy()
    allowed = {spec.name: spec for spec in behaviors_allowed(ctx.scene, policy)}
    if not allowed:
        return []

    candidates: list[BehaviorCandidate] = []
    night = ctx.world_time.time_of_day == "night"

    # 危险自保：玩家倒地 → 高优先级提醒（FR-024 danger_self_preserve）
    if ctx.player.is_downed and "alert_player" in allowed:
        candidates.append(
            BehaviorCandidate(
                behavior="alert_player",
                category="danger_self_preserve",
                priority=allowed["alert_player"].priority,
                target_id=None,
                trigger_source="player_downed",
                reason_codes=["PLAYER_DOWNED"],
                payload={},
            )
        )

    # 剧情事件类目：首次进入区域 → 提醒玩家（SDD 归 story_event）
    if ctx.region is not None and ctx.region.first_visit and "alert_player" in allowed:
        candidates.append(
            BehaviorCandidate(
                behavior="alert_player",
                category="story_event",
                priority=allowed["alert_player"].priority,
                target_id=None,
                trigger_source="region_first_visit",
                reason_codes=["REGION_FIRST_VISIT", ctx.region.region_id],
                payload={"region_id": ctx.region.region_id},
            )
        )

    # 日常自主：低血量休整（camp/idle 才有 rest）
    if ctx.companion.hp_percent < 40 and "rest" in allowed:
        candidates.append(
            BehaviorCandidate(
                behavior="rest",
                category="routine_autonomy",
                priority=allowed["rest"].priority,
                target_id=None,
                trigger_source="low_hp",
                reason_codes=["COMPANION_HP_LOW"],
                payload={"duration_seconds": "30"},
            )
        )

    # 日常自主：夜晚休整（camp/idle）
    if night and "rest" in allowed:
        candidates.append(
            BehaviorCandidate(
                behavior="rest",
                category="routine_autonomy",
                priority=allowed["rest"].priority,
                target_id=None,
                trigger_source="night_rest",
                reason_codes=["TIME_OF_DAY_NIGHT"],
                payload={"duration_seconds": "30"},
            )
        )

    # 日常自主：夜间自言自语（关系阶段 ≥ friendly 才主动表露内心）
    if night and "self_talk" in allowed and relationship_stage in {"friendly", "close"}:
        candidates.append(
            BehaviorCandidate(
                behavior="self_talk",
                category="routine_autonomy",
                priority=allowed["self_talk"].priority,
                target_id=None,
                trigger_source="night_self_talk",
                reason_codes=["TIME_OF_DAY_NIGHT", "RELATIONSHIP_STAGE_HIGH"],
                payload={"topic": "night"},
            )
        )

    # 日常自主：可交互物（notable → inspect/observe；item 且近 → pickup）
    for target in ctx.interactables:
        if target.notable and "inspect" in allowed and _target_ok(allowed["inspect"], target):
            candidates.append(
                BehaviorCandidate(
                    behavior="inspect",
                    category="routine_autonomy",
                    priority=allowed["inspect"].priority,
                    target_id=target.object_id,
                    trigger_source="notable_object",
                    reason_codes=["NOTABLE_OBJECT", target.object_id],
                    payload={"object_id": target.object_id},
                )
            )
        if target.notable and "observe" in allowed and _target_ok(allowed["observe"], target):
            candidates.append(
                BehaviorCandidate(
                    behavior="observe",
                    category="routine_autonomy",
                    priority=allowed["observe"].priority,
                    target_id=target.object_id,
                    trigger_source="notable_object",
                    reason_codes=["NOTABLE_OBJECT", target.object_id],
                    payload={"object_id": target.object_id},
                )
            )
        if "pickup" in allowed and _target_ok(allowed["pickup"], target):
            candidates.append(
                BehaviorCandidate(
                    behavior="pickup",
                    category="routine_autonomy",
                    priority=allowed["pickup"].priority,
                    target_id=target.object_id,
                    trigger_source="nearby_item",
                    reason_codes=["NEARBY_ITEM", target.object_id],
                    payload={"object_id": target.object_id},
                )
            )

    # 兜底：静止观察（无目标；任何非战斗域都有 observe 或以 wait 代替）
    if not any(c.behavior == "observe" for c in candidates):
        if "observe" in allowed:
            candidates.append(
                BehaviorCandidate(
                    behavior="observe",
                    category="routine_autonomy",
                    priority=allowed["observe"].priority,
                    target_id=None,
                    trigger_source="default",
                    reason_codes=["DEFAULT_OBSERVE"],
                    payload={},
                )
            )
        elif "wait" in allowed:
            candidates.append(
                BehaviorCandidate(
                    behavior="wait",
                    category="routine_autonomy",
                    priority=allowed["wait"].priority,
                    target_id=None,
                    trigger_source="default",
                    reason_codes=["DEFAULT_WAIT"],
                    payload={},
                )
            )

    return candidates
