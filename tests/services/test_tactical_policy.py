"""`data/policy/tactical_policy.yaml` 加载与校验测试（策划书 §5.1 第 4 层）。"""

from pathlib import Path

import pytest

from app.services.tactical.policy import (
    TacticalPolicyError,
    load_tactical_policy,
    reset_policy_cache,
)

POLICY_PATH = Path(__file__).resolve().parents[2] / "data" / "policy" / "tactical_policy.yaml"


def test_repo_policy_loads_with_expected_defaults() -> None:
    """仓库内的策略文件可加载，且阈值与迁移前的硬编码值一致（行为零变化）。"""
    policy = load_tactical_policy()
    assert policy.revision
    assert policy.thresholds.player_hp_critical == 30
    assert policy.thresholds.player_hp_low == 70
    assert policy.thresholds.companion_mp_low == 20
    assert policy.thresholds.boss_melee_range_m == 5.0
    assert policy.priorities.major_heal == 95
    assert policy.priorities.event_burst == 85


def test_missing_file_raises() -> None:
    with pytest.raises(TacticalPolicyError):
        load_tactical_policy(Path("data/policy/__nonexistent__.yaml"))


def test_invalid_threshold_order_raises(tmp_path: Path) -> None:
    """player_hp_low 必须 >= player_hp_critical，否则策略自相矛盾。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
revision: r
event_revision: e
thresholds:
  player_hp_critical: 70
  player_hp_low: 30
  companion_mp_low: 20
  boss_melee_range_m: 5.0
priorities:
  major_heal: 95
  quick_heal: 85
  shield: 80
  burst: 85
  burst_pending_stun: 80
  retreat: 90
  follow: 40
  event_major_heal: 90
  event_quick_heal: 90
  event_shield: 70
  event_burst: 85
""",
        encoding="utf-8",
    )
    with pytest.raises(TacticalPolicyError, match="player_hp_low"):
        load_tactical_policy(bad)


def test_missing_field_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
revision: r
event_revision: e
thresholds:
  player_hp_critical: 30
priorities:
  major_heal: 95
""",
        encoding="utf-8",
    )
    with pytest.raises(TacticalPolicyError, match="player_hp_low"):
        load_tactical_policy(bad)


def test_resolver_thresholds_come_from_yaml() -> None:
    """resolver 导出的常量与 rl 基线引用的阈值来自策略文件（同源保证）。"""
    import app.services.tactical.resolver as resolver

    policy = load_tactical_policy(POLICY_PATH)
    assert resolver.PLAYER_HP_CRITICAL == policy.thresholds.player_hp_critical
    assert resolver.COMPANION_MP_LOW == policy.thresholds.companion_mp_low
    assert resolver.POLICY_REVISION == policy.revision
    reset_policy_cache()  # resolver 导入期已缓存，避免影响后续用例
