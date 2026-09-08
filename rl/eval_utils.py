"""评测工具：跑 N 局、按指标聚合（rl_train / rl_eval 脚本共用）。

核心盯防指标是「眩晕窗口 explosion 施放率」：奖励 hacking（noop 拖时间）
主要靠它与胜率联合判定（详见 docs/RL可行性分析与框架设计.md §8）。
"""

import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rl.features import extract_observation_from_state
from rl.sim.constants import ACTION_EXPLOSION
from rl.sim.core import BossSim

if TYPE_CHECKING:
    from rl.policy.base import ActingPolicy


@dataclass
class EpisodeResult:
    reward: float
    ticks: int
    done_reason: str
    explosion_in_stun: int = 0
    explosion_total: int = 0


@dataclass
class EvalReport:
    episodes: int
    mean_reward: float
    win_rate: float            # boss_dead 占比
    player_survival_rate: float
    mean_ticks: float
    explosion_in_stun_rate: float  # 眩晕窗口施放占比（核心盯防）
    reasons: dict = field(default_factory=dict)


def run_episode(sim: BossSim, policy: "ActingPolicy", seed: int) -> EpisodeResult:
    sim.reset(seed=seed)
    total, ticks = 0.0, 0
    result = EpisodeResult(reward=0.0, ticks=0, done_reason="")
    from rl.rewards import compute_reward  # 局部导入避免循环

    while True:
        state = sim.state
        obs = extract_observation_from_state(state)
        action = policy.select_action(obs, state)
        _, events, done_reason = sim.step(action)
        reward = compute_reward(events, state, done_reason)
        total += reward
        ticks += 1
        if action == ACTION_EXPLOSION:
            result.explosion_total += 1
            if events.boss_stunned_at_action:
                result.explosion_in_stun += 1
        if done_reason:
            result.reward, result.ticks, result.done_reason = total, ticks, done_reason
            return result


def aggregate(results: list[EpisodeResult]) -> EvalReport:
    n = len(results)
    stun_casts = sum(r.explosion_in_stun for r in results)
    total_casts = sum(r.explosion_total for r in results)
    reasons: dict[str, int] = {}
    for r in results:
        reasons[r.done_reason] = reasons.get(r.done_reason, 0) + 1
    return EvalReport(
        episodes=n,
        mean_reward=statistics.fmean(r.reward for r in results),
        win_rate=reasons.get("boss_dead", 0) / n,
        player_survival_rate=(n - reasons.get("player_downed", 0) - reasons.get("companion_downed", 0)) / n,
        mean_ticks=statistics.fmean(r.ticks for r in results),
        explosion_in_stun_rate=stun_casts / total_casts if total_casts else 0.0,
        reasons=reasons,
    )


def evaluate_policy(sim: BossSim, policy: "ActingPolicy", episodes: int, base_seed: int = 0) -> EvalReport:
    """固定种子序列跑 N 局（保证策略间可比），聚合成报告。"""
    results = [run_episode(sim, policy, seed=base_seed + i) for i in range(episodes)]
    return aggregate(results)
