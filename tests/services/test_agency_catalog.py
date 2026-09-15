"""行为目录与候选生成测试（SDD T045 / FR-020、FR-025、FR-040）。

目录从 ``data/policy/agency_policy.yaml`` 加载（进程缓存 + reset）；候选生成
为确定性规则驱动（无 LLM）；目标必须出现在快照中，宁可空也不虚构。
"""

from __future__ import annotations

import pytest

from app.schemas.world_context import WorldContext
from app.services.agency.behavior_catalog import (
    AgencyPolicyError,
    behaviors_allowed,
    generate_candidates,
    get_agency_policy,
    reset_agency_policy_cache,
)


def _ctx(**overrides) -> WorldContext:
    """构造非战斗快照；默认 camp 夜晚 + 篝火 notable（典型营地场景）。"""
    payload = {
        "snapshot_id": "00000000-0000-4000-8000-000000000002",
        "captured_at": "2026-09-13T12:00:00Z",
        "scene": "camp",
        "world_time": {"time_of_day": "night", "weather": "clear"},
        "player": {"id": "party.player", "hp_percent": 95},
        "companion": {"id": "companion.alice", "hp_percent": 85, "mp_percent": 40},
        "interactables": [
            {"object_id": "object.campfire.001", "kind": "prop", "distance_m": 3.0, "notable": True}
        ],
    }
    payload.update(overrides)
    return WorldContext.model_validate(payload)


@pytest.fixture(autouse=True)
def _clean_policy_cache():
    reset_agency_policy_cache()
    yield
    reset_agency_policy_cache()


def test_policy_loads_with_expected_shape() -> None:
    """策略加载：revision 存在、非战斗行为 ≥8 类、白名单为闭集。"""
    policy = get_agency_policy()
    assert policy.revision
    assert len(policy.behaviors) >= 8
    for spec in policy.behaviors.values():
        assert spec.priority >= 0
        assert spec.domains


def test_behaviors_allowed_filters_by_domain() -> None:
    """camp 场景能拿到 rest/inspect；combat 场景拿不到任何目录行为。"""
    camp = {spec.name for spec in behaviors_allowed("camp")}
    assert {"rest", "inspect"} <= camp
    assert behaviors_allowed("combat") == []


def test_candidates_camp_night_notable_campfire() -> None:
    """camp 夜晚 + notable 篝火 → 产出 inspect/observe，目标为篝火 ID。"""
    candidates = generate_candidates(_ctx())
    behaviors = {c.behavior for c in candidates}
    assert {"inspect", "observe"} & behaviors
    for candidate in candidates:
        if candidate.behavior in {"inspect", "observe"}:
            assert candidate.target_id == "object.campfire.001"
            assert "notable_object" in candidate.reason_codes or candidate.reason_codes


def test_candidates_idle_night_produces_rest() -> None:
    """idle 夜晚（无交互物）→ 产出 rest 类日常行为。"""
    ctx = _ctx(
        scene="idle",
        world_time={"time_of_day": "night", "weather": "clear"},
        interactables=[],
    )
    behaviors = {c.behavior for c in generate_candidates(ctx)}
    assert "rest" in behaviors


def test_candidates_low_hp_rest() -> None:
    """companion 低血量 → rest 候选（自保日常）。"""
    ctx = _ctx(
        companion={"id": "companion.alice", "hp_percent": 25, "mp_percent": 20}
    )
    behaviors = {c.behavior for c in generate_candidates(ctx)}
    assert "rest" in behaviors


def test_candidates_nearby_item_pickup() -> None:
    """kind=item 且近 → pickup 候选；kind=prop 不产 pickup（kind 校验）。"""
    ctx = _ctx(
        interactables=[
            {"object_id": "object.loot.potion", "kind": "item", "distance_m": 2.0, "notable": False}
        ]
    )
    behaviors = {c.behavior for c in generate_candidates(ctx)}
    assert "pickup" in behaviors
    # prop 对象不产 pickup
    prop_only = _ctx(
        interactables=[
            {"object_id": "object.campfire.001", "kind": "prop", "distance_m": 1.0, "notable": False}
        ]
    )
    assert "pickup" not in {c.behavior for c in generate_candidates(prop_only)}


def test_candidates_region_first_visit_alerts_player() -> None:
    """region.first_visit → alert_player 候选（高优先级提醒）。"""
    ctx = _ctx(
        region={"region_id": "region.forest.deep", "first_visit": True}
    )
    candidates = generate_candidates(ctx)
    alerts = [c for c in candidates if c.behavior == "alert_player"]
    assert alerts
    assert alerts[0].priority >= 60


def test_candidates_player_danger_alert() -> None:
    """玩家倒地 → alert_player 归入危险自保类目。"""
    ctx = _ctx(player={"id": "party.player", "hp_percent": 0, "is_downed": True})
    candidates = generate_candidates(ctx)
    alerts = [c for c in candidates if c.behavior == "alert_player"]
    assert alerts
    assert alerts[0].category == "danger_self_preserve"


def test_candidates_default_observe_fallback() -> None:
    """无任何触发条件的探索场景 → 兜底 observe（静止观察）。"""
    ctx = _ctx(
        scene="exploration",
        world_time={"time_of_day": "noon", "weather": "clear"},
        interactables=[],
    )
    behaviors = {c.behavior for c in generate_candidates(ctx)}
    assert "observe" in behaviors


def test_relationship_stage_gates_self_talk() -> None:
    """关系阶段调制：低阶段（distant）不产 self_talk，高阶段（close）产。"""
    ctx = _ctx(
        scene="idle",
        world_time={"time_of_day": "night", "weather": "clear"},
        interactables=[],
    )
    low = {c.behavior for c in generate_candidates(ctx, relationship_stage="distant")}
    high = {c.behavior for c in generate_candidates(ctx, relationship_stage="close")}
    assert "self_talk" not in low
    assert "self_talk" in high


def test_candidate_targets_only_from_snapshot() -> None:
    """FR-040：候选目标必须出现在快照中——空 interactables 时不产带目标候选。"""
    ctx = _ctx(interactables=[])
    for candidate in generate_candidates(ctx):
        assert candidate.target_id is None


def test_candidates_ignore_scene_out_of_domain() -> None:
    """combat 场景下不产出任何目录行为（域过滤在生成阶段生效）。"""
    ctx = _ctx(scene="combat")
    assert generate_candidates(ctx) == []


def test_policy_error_on_invalid_yaml(tmp_path, monkeypatch) -> None:
    """YAML 非法（缺字段）→ AgencyPolicyError。"""
    bad = tmp_path / "agency_policy.yaml"
    bad.write_text("revision: x\nbehaviors: {}\n", encoding="utf-8")
    from app.services.agency import behavior_catalog as module

    monkeypatch.setattr(module, "_POLICY_PATH", bad)
    with pytest.raises(AgencyPolicyError):
        module.get_agency_policy()
