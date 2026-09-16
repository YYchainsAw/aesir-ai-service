"""活动场景判定测试（SDD T044 / FR-019、FR-023）。

场景判定信任 UE 上报的 ``scene`` 字段，仅做防御性一致性检查；战斗域排除
生活类行为；禁打断标志聚合为单一原因名（与 agency_policy.yaml 对齐）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.world_context import WorldContext
from app.services.agency.domain import (
    allows_lifestyle,
    domain_for,
    no_interrupt_reason,
    resolve_scene,
)

_GOLDEN_DIR = Path(__file__).resolve().parents[2] / "data" / "golden"


def _load_golden(name: str) -> WorldContext:
    return WorldContext.model_validate(
        json.loads((_GOLDEN_DIR / name).read_text(encoding="utf-8"))
    )


def _ctx(**overrides) -> WorldContext:
    """手工构造非战斗快照（默认 idle、无交互物、无禁打断标志）。"""
    payload = {
        "snapshot_id": "00000000-0000-4000-8000-000000000001",
        "captured_at": "2026-09-13T12:00:00Z",
        "scene": "idle",
        "player": {"id": "party.player", "hp_percent": 90},
        "companion": {"id": "companion.alice", "hp_percent": 90, "mp_percent": 70},
    }
    payload.update(overrides)
    return WorldContext.model_validate(payload)


def test_golden_snapshots_resolve_expected_scenes() -> None:
    """四个非战斗 golden 快照各自判出对应场景。"""
    cases = {
        "world_snapshot_idle.json": "idle",
        "world_snapshot_exploration.json": "exploration",
        "world_snapshot_camp.json": "camp",
    }
    for filename, expected in cases.items():
        assert resolve_scene(_load_golden(filename)) == expected


def test_all_five_scenes_pass_through() -> None:
    """UE 上报的场景即判定结果（信任上报，透传）。"""
    for scene in ("combat", "exploration", "camp", "conversation", "idle"):
        assert resolve_scene(_ctx(scene=scene)) == scene


def test_domain_for_maps_scene_one_to_one() -> None:
    """活动场景 → 指令域一一映射（同名透传）。"""
    for scene in ("combat", "exploration", "camp", "conversation", "idle"):
        assert domain_for(scene) == scene


def test_combat_domain_excludes_lifestyle_behaviors() -> None:
    """FR-019：战斗域排除生活类行为。"""
    assert allows_lifestyle("combat") is False
    for scene in ("exploration", "camp", "conversation", "idle"):
        assert allows_lifestyle(scene) is True


def test_no_interrupt_reason_none_when_clear() -> None:
    """无禁打断标志时返回 None。"""
    assert no_interrupt_reason(_ctx()) is None


def test_no_interrupt_reason_aggregates_each_flag() -> None:
    """四种禁打断标志各自命中，原因名与策略 no_interrupt_when 名单对齐。"""
    assert no_interrupt_reason(_ctx(cutscene_playing=True)) == "cutscene_playing"
    assert no_interrupt_reason(_ctx(player_speaking=True)) == "player_speaking"
    assert no_interrupt_reason(_ctx(ui_popup=True)) == "ui_popup"
    casting = _ctx(
        companion={
            "id": "companion.alice",
            "hp_percent": 90,
            "mp_percent": 70,
            "is_casting": True,
        }
    )
    assert no_interrupt_reason(casting) == "npc_casting"


def test_no_interrupt_reason_reports_one_cause() -> None:
    """多标志同时命中时返回单一（首个）原因，可解释且确定。"""
    reason = no_interrupt_reason(_ctx(cutscene_playing=True, player_speaking=True))
    assert reason in {"cutscene_playing", "player_speaking"}


def test_scene_wins_over_embedded_combat_context() -> None:
    """scene 与内嵌 combat 快照矛盾时以 scene 为准（防御性，不猜测）。"""
    from app.schemas.combat_context import make_combat_context

    ctx = _ctx(scene="idle", combat=make_combat_context(player_hp=80))
    assert resolve_scene(ctx) == "idle"
    assert allows_lifestyle(resolve_scene(ctx)) is True
