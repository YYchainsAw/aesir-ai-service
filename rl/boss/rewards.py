"""Versioned, explainable reward terms for the Boss policy."""

from dataclasses import dataclass

from rl.boss.sim import BossStepEvents

REWARD_REVISION = "boss-reward-002"


@dataclass(frozen=True)
class BossRewardWeights:
    damage_dealt: float = 5.0
    damage_received: float = -4.0
    successful_dodge: float = 0.25
    successful_defend: float = 0.20
    interrupt: float = 0.15
    invalid_action: float = -0.25
    repeated_action: float = -0.05
    repeated_action_penalty_cap: int = 5
    decision_step: float = -0.01
    victory: float = 10.0
    defeat: float = -10.0
    timeout: float = -1.0


def compute_reward(
    events: BossStepEvents,
    terminal_reason: str | None,
    weights: BossRewardWeights | None = None,
) -> tuple[float, dict[str, float]]:
    w = weights or BossRewardWeights()
    terms = {
        "damage_dealt": events.damage_dealt * w.damage_dealt,
        "damage_received": events.damage_received * w.damage_received,
        "decision_step": w.decision_step,
    }
    if events.successful_dodge:
        terms["successful_dodge"] = w.successful_dodge
    if events.successful_defend:
        terms["successful_defend"] = w.successful_defend
    if events.interrupted_target:
        terms["interrupt"] = w.interrupt
    if not events.accepted and events.result != "state_locked":
        terms["invalid_action"] = w.invalid_action
    if events.repeat_count > 2:
        repeated_steps = min(
            events.repeat_count - 2,
            w.repeated_action_penalty_cap,
        )
        terms["repeated_action"] = w.repeated_action * repeated_steps
    if terminal_reason == "boss_victory":
        terms["terminal"] = w.victory
    elif terminal_reason == "boss_defeat":
        terms["terminal"] = w.defeat
    elif terminal_reason == "timeout":
        terms["terminal"] = w.timeout
    return float(sum(terms.values())), terms
