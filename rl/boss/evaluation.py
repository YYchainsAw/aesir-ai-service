"""Reproducible metrics for Behavior Tree versus RL Boss experiments."""

from collections import Counter
from dataclasses import dataclass, field
import statistics

from rl.boss.policy import BossPolicy
from rl.boss.rewards import REWARD_REVISION, compute_reward
from rl.boss.sim import SIMULATION_REVISION, BossPolicySim, PLAYER_PROFILES


@dataclass(frozen=True)
class EpisodeMetrics:
    seed: int
    player_profile: str
    result: str
    decisions: int
    total_reward: float
    damage_dealt: float
    damage_received: float
    accepted_actions: int
    rejected_actions: int
    state_locked_decisions: int
    repeated_actions: int
    action_counts: dict[str, int]


@dataclass(frozen=True)
class EvaluationReport:
    policy_name: str
    schema_version: int
    simulation_revision: str
    reward_revision: str
    episodes: int
    boss_win_rate: float
    boss_defeat_rate: float
    timeout_rate: float
    mean_decisions: float
    mean_reward: float
    mean_damage_dealt: float
    mean_damage_received: float
    rejected_action_rate: float
    state_locked_rate: float
    repeated_action_rate: float
    action_distribution: dict[str, float]
    results_by_profile: dict[str, dict[str, int]] = field(default_factory=dict)


def run_episode(
    policy: BossPolicy,
    *,
    seed: int,
    player_profile: str,
) -> EpisodeMetrics:
    sim = BossPolicySim(seed=seed, profile=player_profile)
    action_counts: Counter[str] = Counter()
    total_reward = 0.0
    damage_dealt = 0.0
    damage_received = 0.0
    accepted = 0
    rejected = 0
    state_locked = 0
    repeated = 0
    terminal_reason: str | None = None

    while terminal_reason is None:
        observation = sim.state.observation()
        action = policy.select_action(observation, sim.state)
        _, events, terminal_reason = sim.step(action)
        reward, _ = compute_reward(events, terminal_reason)
        total_reward += reward
        damage_dealt += events.damage_dealt
        damage_received += events.damage_received
        if events.result == "state_locked":
            state_locked += 1
        else:
            action_counts[events.action.name] += 1
            accepted += int(events.accepted)
            rejected += int(not events.accepted)
            repeated += int(events.repeat_count > 2)

    return EpisodeMetrics(
        seed=seed,
        player_profile=player_profile,
        result=terminal_reason,
        decisions=sim.state.step,
        total_reward=total_reward,
        damage_dealt=damage_dealt,
        damage_received=damage_received,
        accepted_actions=accepted,
        rejected_actions=rejected,
        state_locked_decisions=state_locked,
        repeated_actions=repeated,
        action_counts=dict(action_counts),
    )


def evaluate_policy(
    policy: BossPolicy,
    *,
    policy_name: str,
    episodes_per_profile: int = 20,
    base_seed: int = 0,
) -> EvaluationReport:
    if episodes_per_profile <= 0:
        raise ValueError("episodes_per_profile must be positive")

    episodes = [
        run_episode(policy, seed=base_seed + index, player_profile=profile)
        for profile in PLAYER_PROFILES
        for index in range(episodes_per_profile)
    ]
    result_counts = Counter(episode.result for episode in episodes)
    action_counts: Counter[str] = Counter()
    results_by_profile: dict[str, dict[str, int]] = {}
    for episode in episodes:
        action_counts.update(episode.action_counts)
        profile_results = results_by_profile.setdefault(episode.player_profile, {})
        profile_results[episode.result] = profile_results.get(episode.result, 0) + 1

    decision_count = sum(episode.decisions for episode in episodes)
    total_actions = sum(action_counts.values())
    actionable_decisions = sum(
        episode.accepted_actions + episode.rejected_actions for episode in episodes
    )
    from rl.boss.contract import SCHEMA_VERSION

    return EvaluationReport(
        policy_name=policy_name,
        schema_version=SCHEMA_VERSION,
        simulation_revision=SIMULATION_REVISION,
        reward_revision=REWARD_REVISION,
        episodes=len(episodes),
        boss_win_rate=result_counts["boss_victory"] / len(episodes),
        boss_defeat_rate=result_counts["boss_defeat"] / len(episodes),
        timeout_rate=result_counts["timeout"] / len(episodes),
        mean_decisions=statistics.fmean(episode.decisions for episode in episodes),
        mean_reward=statistics.fmean(episode.total_reward for episode in episodes),
        mean_damage_dealt=statistics.fmean(episode.damage_dealt for episode in episodes),
        mean_damage_received=statistics.fmean(
            episode.damage_received for episode in episodes
        ),
        rejected_action_rate=(
            sum(episode.rejected_actions for episode in episodes) / actionable_decisions
        ),
        state_locked_rate=(
            sum(episode.state_locked_decisions for episode in episodes) / decision_count
        ),
        repeated_action_rate=(
            sum(episode.repeated_actions for episode in episodes) / actionable_decisions
        ),
        action_distribution={
            action: count / total_actions for action, count in sorted(action_counts.items())
        },
        results_by_profile=results_by_profile,
    )
