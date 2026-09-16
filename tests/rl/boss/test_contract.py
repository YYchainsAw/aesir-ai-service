"""Dependency-free tests for the Boss policy contract and simulator."""

import pytest

from rl.boss.contract import (
    BossAction,
    FEATURE_NAMES,
    OBSERVATION_DIM,
    OBSERVATION_HIGH,
    OBSERVATION_LOW,
    SCHEMA_VERSION,
    make_action_mask,
)
from rl.boss.evaluation import evaluate_policy, run_episode
from rl.boss.policy import RuleBossPolicy
from rl.boss.rewards import REWARD_REVISION, BossRewardWeights, compute_reward
from rl.boss.sim import BossPolicySim, BossStepEvents


def test_contract_matches_unreal_schema_v4() -> None:
    assert SCHEMA_VERSION == 4
    assert OBSERVATION_DIM == 26
    assert FEATURE_NAMES == (
        "boss_health_ratio",
        "target_health_ratio",
        "normalized_distance",
        "facing_alignment",
        "has_line_of_sight",
        "boss_stunned",
        "boss_attacking",
        "target_blocking",
        "target_attacking",
        "target_dead",
        "boss_poise_ratio",
        "target_guard_pressure_ratio",
        "target_dodging",
        "recent_target_attack_rate",
        "recent_target_block_rate",
        "recent_target_dodge_rate",
        "distance_trend",
        "light_attack_available",
        "heavy_attack_available",
        "defend_available",
        "dodge_available",
        "pursue_available",
        "disengage_available",
        "use_ability_available",
        "gap_closer_skill_available",
        "unblockable_area_skill_available",
    )
    assert [action.value for action in BossAction] == list(range(9))
    assert OBSERVATION_LOW == (0.0,) * OBSERVATION_DIM
    assert OBSERVATION_HIGH == (1.0,) * OBSERVATION_DIM


def test_action_availability_tracks_stun_and_cooldown() -> None:
    sim = BossPolicySim(seed=0, profile="defensive")
    assert sim.state.observation()[17:] == (1.0,) * len(BossAction)

    sim.state.cooldown_steps[BossAction.DODGE] = 2
    assert sim.state.observation()[20] == 0.0
    assert make_action_mask(sim.state.observation())[BossAction.DODGE] is False

    sim.state.boss_stunned_steps = 2
    assert sim.state.observation()[17:] == (0.0,) * len(BossAction)
    assert make_action_mask(sim.state.observation()) == (True,) * len(BossAction)


def test_repeated_action_penalty_is_capped() -> None:
    weights = BossRewardWeights()
    events = BossStepEvents(
        action=BossAction.HEAVY_ATTACK,
        accepted=False,
        result="invalid_range_or_facing",
        repeat_count=100,
    )
    _, terms = compute_reward(events, terminal_reason=None, weights=weights)
    assert REWARD_REVISION == "boss-reward-002"
    assert terms["repeated_action"] == pytest.approx(
        weights.repeated_action * weights.repeated_action_penalty_cap
    )


def test_same_seed_and_profile_are_reproducible() -> None:
    actions = [4, 4, 1, 3, 0, 2, 5, 4, 6] * 5
    trajectories = []
    for _ in range(2):
        sim = BossPolicySim(seed=11, profile="evasive")
        trajectory = []
        for action in actions:
            state, events, terminal_reason = sim.step(action)
            reward, terms = compute_reward(events, terminal_reason)
            trajectory.append((state.observation(), reward, terms, terminal_reason))
            if terminal_reason:
                break
        trajectories.append(trajectory)
    assert trajectories[0] == trajectories[1]


def test_player_profiles_produce_different_trajectories() -> None:
    trajectories = {}
    for profile in ("aggressive", "defensive", "evasive"):
        sim = BossPolicySim(seed=5, profile=profile)
        trajectory = []
        for _ in range(20):
            state, events, _ = sim.step(BossAction.PURSUE)
            trajectory.append(
                (state.target_attacking, state.target_blocking, events.damage_received)
            )
        trajectories[profile] = trajectory
    assert len({tuple(value) for value in trajectories.values()}) == 3


def test_committed_attack_miss_is_accepted_and_starts_cooldown() -> None:
    sim = BossPolicySim(seed=7, profile="aggressive")
    _, events, terminal_reason = sim.step(BossAction.HEAVY_ATTACK)
    reward, terms = compute_reward(events, terminal_reason)
    assert events.accepted is True
    assert events.result == "accepted_miss"
    assert sim.state.cooldown_steps[BossAction.HEAVY_ATTACK] == 7
    assert "invalid_action" not in terms
    assert reward < 0.0


def test_invalid_movement_action_has_named_negative_reward() -> None:
    sim = BossPolicySim(seed=7, profile="aggressive")
    sim.state.normalized_distance = 0.05
    _, events, terminal_reason = sim.step(BossAction.PURSUE)
    reward, terms = compute_reward(events, terminal_reason)
    assert events.accepted is False
    assert events.result == "already_at_goal"
    assert terms["invalid_action"] < 0.0
    assert reward < 0.0


def test_rule_baseline_reaches_terminal_state() -> None:
    result = run_episode(RuleBossPolicy(), seed=13, player_profile="defensive")
    assert result.result in ("boss_victory", "boss_defeat", "timeout")
    assert result.decisions > 0
    assert (
        sum(result.action_counts.values()) + result.state_locked_decisions
        == result.decisions
    )


def test_evaluation_reports_defense_metrics_by_profile() -> None:
    report = evaluate_policy(
        RuleBossPolicy(),
        policy_name="BehaviorTreeRuleBaseline",
        episodes_per_profile=2,
        base_seed=21,
    )
    assert report.episodes == 6
    assert report.simulation_revision == "boss-sim-003"
    assert set(report.results_by_profile) == {"aggressive", "defensive", "evasive"}
    assert 0.0 <= report.boss_win_rate <= 1.0
    assert 0.0 <= report.rejected_action_rate <= 1.0
    assert 0.0 <= report.state_locked_rate <= 1.0
    assert sum(report.action_distribution.values()) == pytest.approx(1.0)
