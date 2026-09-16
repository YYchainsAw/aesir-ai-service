"""不可执行防护测试（SDD T048 / FR-025、FR-028、FR-040）。

目标不存在 / 类型不符 / 距离超阈值 / 场景外行为 → 不虚构行为，
宁可返回空候选（由主入口转空动作 + 原因码）。
"""

from __future__ import annotations

import pytest

from app.schemas.world_context import WorldContext
from app.services.agency.behavior_catalog import (
    generate_candidates,
    get_agency_policy,
    reset_agency_policy_cache,
)
from app.services.agency.domain import no_interrupt_reason


def _ctx(**overrides) -> WorldContext:
    payload = {
        "snapshot_id": "00000000-0000-4000-8000-000000000003",
        "captured_at": "2026-09-13T12:00:00Z",
        "scene": "exploration",
        "world_time": {"time_of_day": "noon", "weather": "clear"},
        "player": {"id": "party.player", "hp_percent": 90},
        "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
        "interactables": [],
    }
    payload.update(overrides)
    return WorldContext.model_validate(payload)


@pytest.fixture(autouse=True)
def _clean_policy_cache():
    reset_agency_policy_cache()
    yield
    reset_agency_policy_cache()


def test_no_candidates_reference_unseen_targets() -> None:
    """快照无 interactables 时，任何候选都不得带目标 ID（不虚构目标）。"""
    for candidate in generate_candidates(_ctx()):
        assert candidate.target_id is None


def test_pickup_only_for_item_kind() -> None:
    """pickup 只对 kind=item；npc/poi 对象不产 pickup。"""
    for kind in ("npc", "poi", "prop"):
        ctx = _ctx(
            interactables=[
                {"object_id": f"object.x.{kind}", "kind": kind, "distance_m": 1.0, "notable": True}
            ]
        )
        assert "pickup" not in {c.behavior for c in generate_candidates(ctx)}


def test_distance_over_limit_drops_targeted_candidate() -> None:
    """距离超出所有带目标行为上限的对象不产任何目标候选。"""
    policy = get_agency_policy()
    targeted_max = max(
        s.max_distance_m for s in policy.behaviors.values() if s.allowed_kinds is not None
    )
    far = targeted_max + 10.0
    ctx = _ctx(
        interactables=[
            {"object_id": "object.ruin.far", "kind": "poi", "distance_m": far, "notable": True}
        ]
    )
    for candidate in generate_candidates(ctx):
        assert candidate.target_id != "object.ruin.far"


def test_combat_scene_yields_no_lifestyle_candidates() -> None:
    """FR-019：战斗场景不产生活类候选（返回空，交回战斗链路）。"""
    assert generate_candidates(_ctx(scene="combat")) == []


def test_no_interrupt_forbids_autonomous_behavior() -> None:
    """禁打断标志命中 → 不发起自主行为（返回原因名）。"""
    for flags in ({"cutscene_playing": True}, {"player_speaking": True}, {"ui_popup": True}):
        reason = no_interrupt_reason(_ctx(**flags))
        assert reason is not None
        assert reason == next(iter(flags))


def test_all_dropped_candidates_mean_not_actionable() -> None:
    """所有候选都被防护规则丢弃 → 空候选（主入口返回空动作 + NOT_ACTIONABLE）。

    构造：notable 对象但距离远且场景为 camp（无兜底 observe 域）→ 候选全被
    距离/kind 防护丢弃，返回空列表而非虚构。
    """
    policy = get_agency_policy()
    far = max(policy.behaviors.values(), key=lambda s: s.max_distance_m).max_distance_m + 50.0
    ctx = _ctx(
        scene="camp",
        world_time={"time_of_day": "noon", "weather": "clear"},
        interactables=[
            {"object_id": "object.ruin.far", "kind": "poi", "distance_m": far, "notable": True}
        ],
        player={"id": "party.player", "hp_percent": 100},
    )
    # camp + 白天 + 无近对象 + 血量正常 → rest（低血/夜晚）不触发
    candidates = generate_candidates(ctx)
    for candidate in candidates:
        assert candidate.target_id != "object.ruin.far"
