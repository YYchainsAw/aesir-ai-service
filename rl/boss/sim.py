"""Deterministic high-level Boss combat simulator.

This simulator is deliberately tactical rather than animation-accurate. One
step equals one policy decision (0.25 seconds); Unreal remains responsible for
navigation, GAS legality, montages, collision, and hit timing.
"""

from dataclasses import dataclass, field
import random

from rl.boss.contract import BossAction, make_observation

SIMULATION_REVISION = "boss-sim-003"


@dataclass(frozen=True)
class PlayerProfile:
    name: str
    attack_probability: float
    block_probability: float
    evade_probability: float
    preferred_distance: float
    attack_range: float
    approach_per_step: float
    attack_damage: float
    poise_damage: float


PLAYER_PROFILES: dict[str, PlayerProfile] = {
    "aggressive": PlayerProfile(
        "aggressive", 0.78, 0.08, 0.08, 0.14, 0.25, 0.09, 0.065, 0.20
    ),
    "defensive": PlayerProfile(
        "defensive", 0.38, 0.52, 0.08, 0.22, 0.27, 0.055, 0.045, 0.14
    ),
    "evasive": PlayerProfile(
        "evasive", 0.42, 0.08, 0.48, 0.36, 0.23, 0.045, 0.05, 0.15
    ),
}


@dataclass
class BossSimConfig:
    decision_seconds: float = 0.25
    max_steps: int = 400
    light_range: float = 0.24
    heavy_range: float = 0.31
    ability_range: float = 0.42
    gap_closer_range: float = 0.72
    area_skill_range: float = 0.34
    pursue_distance: float = 0.10
    disengage_distance: float = 0.14
    stun_duration_steps: int = 6


@dataclass
class BossCombatState:
    step: int = 0
    boss_health_ratio: float = 1.0
    target_health_ratio: float = 1.0
    normalized_distance: float = 0.55
    facing_alignment: float = 1.0
    has_line_of_sight: bool = True
    boss_stunned_steps: int = 0
    boss_attacking: bool = False
    target_blocking: bool = False
    target_attacking: bool = False
    target_dodging: bool = False
    target_guard_pressure_ratio: float = 0.0
    distance_trend: float = 0.5
    boss_poise: float = 0.0
    cooldown_steps: dict[BossAction, int] = field(default_factory=dict)
    last_action: BossAction | None = None
    consecutive_action_count: int = 0
    recent_target_attacks: list[float] = field(default_factory=list)
    recent_target_blocks: list[float] = field(default_factory=list)
    recent_target_dodges: list[float] = field(default_factory=list)

    @property
    def boss_stunned(self) -> bool:
        return self.boss_stunned_steps > 0

    @property
    def target_dead(self) -> bool:
        return self.target_health_ratio <= 0.0

    @property
    def boss_dead(self) -> bool:
        return self.boss_health_ratio <= 0.0

    def is_action_available(self, action: BossAction) -> bool:
        """Mirror the simulator's side-effect-free action legality checks."""
        return (
            not self.boss_stunned
            and self.cooldown_steps.get(action, 0) <= 0
        )

    def observation(self):
        recent_attack_rate = self._recent_rate(self.recent_target_attacks)
        recent_block_rate = self._recent_rate(self.recent_target_blocks)
        recent_dodge_rate = self._recent_rate(self.recent_target_dodges)
        return make_observation(
            (
                self.boss_health_ratio,
                self.target_health_ratio,
                self.normalized_distance,
                self.facing_alignment,
                float(self.has_line_of_sight),
                float(self.boss_stunned),
                float(self.boss_attacking),
                float(self.target_blocking),
                float(self.target_attacking),
                float(self.target_dead),
                max(0.0, min(1.0, 1.0 - self.boss_poise)),
                self.target_guard_pressure_ratio,
                float(self.target_dodging),
                recent_attack_rate,
                recent_block_rate,
                recent_dodge_rate,
                self.distance_trend,
                *(float(self.is_action_available(action)) for action in BossAction),
            )
        )

    @staticmethod
    def _recent_rate(samples: list[float]) -> float:
        return sum(samples) / len(samples) if samples else 0.0


@dataclass
class BossStepEvents:
    action: BossAction
    accepted: bool = False
    result: str = "accepted"
    damage_dealt: float = 0.0
    damage_received: float = 0.0
    successful_dodge: bool = False
    successful_defend: bool = False
    interrupted_target: bool = False
    repeat_count: int = 1
    reward_terms: dict[str, float] = field(default_factory=dict)


class BossPolicySim:
    """Small reproducible environment used to train high-level Boss choices."""

    def __init__(
        self,
        seed: int = 0,
        profile: str = "aggressive",
        config: BossSimConfig | None = None,
    ) -> None:
        self.config = config or BossSimConfig()
        self._profile_name = self._validate_profile(profile)
        self._seed = seed
        self._rng = random.Random(seed)
        self.state = BossCombatState()

    @property
    def profile(self) -> PlayerProfile:
        return PLAYER_PROFILES[self._profile_name]

    def reset(self, seed: int | None = None, profile: str | None = None) -> BossCombatState:
        if seed is not None:
            self._seed = seed
        if profile is not None:
            self._profile_name = self._validate_profile(profile)
        self._rng = random.Random(self._seed)
        self.state = BossCombatState()
        return self.state

    def step(self, action_value: int) -> tuple[BossCombatState, BossStepEvents, str | None]:
        if self._terminal_reason() is not None:
            raise RuntimeError("episode already finished; call reset()")

        action = BossAction(action_value)
        state = self.state
        distance_before = state.normalized_distance
        cooldowns_to_tick = set(state.cooldown_steps)
        was_stunned = state.boss_stunned

        events = BossStepEvents(action=action)
        self._select_player_intent()

        if was_stunned:
            # The runtime executor pauses tactical execution while state-locked.
            # The submitted action is ignored rather than treated as illegal.
            events.result = "state_locked"
        elif state.cooldown_steps.get(action, 0) > 0:
            self._track_repetition(action, events)
            events.result = "cooldown"
        else:
            self._track_repetition(action, events)
            self._apply_boss_action(action, events)

        self._advance_action_timers(
            cooldowns_to_tick,
            was_stunned=was_stunned,
        )
        self._resolve_player_action(action, events)
        # A simulator step spans the complete high-level action. The next
        # observation is sampled only after that action has finished.
        state.boss_attacking = False
        distance_delta = state.normalized_distance - distance_before
        state.distance_trend = max(
            0.0,
            min(1.0, 0.5 + distance_delta / 0.30),
        )
        state.step += 1
        state.boss_health_ratio = max(0.0, state.boss_health_ratio)
        state.target_health_ratio = max(0.0, state.target_health_ratio)
        return state, events, self._terminal_reason()

    def _select_player_intent(self) -> None:
        state = self.state
        profile = self.profile
        state.target_attacking = False
        state.target_blocking = False
        state.target_dodging = False

        if state.normalized_distance > profile.preferred_distance:
            state.normalized_distance = max(
                0.05, state.normalized_distance - profile.approach_per_step
            )

        if state.normalized_distance <= profile.attack_range:
            roll = self._rng.random()
            if roll < profile.attack_probability:
                state.target_attacking = True
            elif roll < profile.attack_probability + profile.block_probability:
                state.target_blocking = True
            elif roll < (
                profile.attack_probability
                + profile.block_probability
                + profile.evade_probability
            ):
                state.target_dodging = True

        self._push_recent_sample(
            state.recent_target_attacks,
            float(state.target_attacking),
        )
        self._push_recent_sample(
            state.recent_target_blocks,
            float(state.target_blocking),
        )
        self._push_recent_sample(
            state.recent_target_dodges,
            float(state.target_dodging),
        )

    def _apply_boss_action(self, action: BossAction, events: BossStepEvents) -> None:
        state = self.state
        if action == BossAction.PURSUE:
            if state.normalized_distance <= 0.08:
                events.result = "already_at_goal"
                return
            state.normalized_distance = max(
                0.05, state.normalized_distance - self.config.pursue_distance
            )
            events.accepted = True
            return

        if action == BossAction.DISENGAGE:
            if state.normalized_distance >= 0.90:
                events.result = "already_at_goal"
                return
            state.normalized_distance = min(
                1.0, state.normalized_distance + self.config.disengage_distance
            )
            state.cooldown_steps[action] = 2
            events.accepted = True
            return

        if action == BossAction.DEFEND:
            state.cooldown_steps[action] = 4
            events.accepted = True
            return

        if action == BossAction.DODGE:
            state.cooldown_steps[action] = 5
            state.normalized_distance = min(1.0, state.normalized_distance + 0.08)
            events.successful_dodge = state.target_attacking
            events.accepted = True
            return

        if action == BossAction.GAP_CLOSER_SKILL:
            state.boss_attacking = True
            state.cooldown_steps[action] = 12
            events.accepted = True
            if (
                not state.has_line_of_sight
                or state.facing_alignment < 0.25
                or state.normalized_distance > self.config.gap_closer_range
            ):
                events.result = "accepted_miss"
                return
            state.normalized_distance = max(
                0.10,
                state.normalized_distance - 0.30,
            )
            self._resolve_boss_attack(action, events)
            return

        if action == BossAction.UNBLOCKABLE_AREA_SKILL:
            state.boss_attacking = True
            state.cooldown_steps[action] = 18
            events.accepted = True
            if (
                not state.has_line_of_sight
                or state.normalized_distance > self.config.area_skill_range
            ):
                events.result = "accepted_miss"
                return
            self._resolve_boss_attack(action, events)
            return

        range_limit = {
            BossAction.LIGHT_ATTACK: self.config.light_range,
            BossAction.HEAVY_ATTACK: self.config.heavy_range,
            BossAction.USE_ABILITY: self.config.ability_range,
        }[action]
        state.boss_attacking = True
        state.cooldown_steps[action] = {
            BossAction.LIGHT_ATTACK: 3,
            BossAction.HEAVY_ATTACK: 7,
            BossAction.USE_ABILITY: 16,
        }[action]
        events.accepted = True

        if (
            state.normalized_distance > range_limit
            or not state.has_line_of_sight
            or state.facing_alignment < 0.25
        ):
            # GAS accepted and committed the action, but the attack did not
            # connect. This matches UE more closely than rejecting activation.
            events.result = "accepted_miss"
            return

        self._resolve_boss_attack(action, events)

    def _resolve_boss_attack(self, action: BossAction, events: BossStepEvents) -> None:
        state = self.state
        damage = {
            BossAction.LIGHT_ATTACK: 0.075,
            BossAction.HEAVY_ATTACK: 0.16,
            BossAction.USE_ABILITY: 0.21,
            BossAction.GAP_CLOSER_SKILL: 0.12,
            BossAction.UNBLOCKABLE_AREA_SKILL: 0.18,
        }[action]
        if state.target_dodging:
            return
        if state.target_blocking and action == BossAction.LIGHT_ATTACK:
            damage *= 0.2
            state.target_guard_pressure_ratio += 0.20
        if state.target_blocking and action == BossAction.HEAVY_ATTACK:
            state.target_guard_pressure_ratio += 0.45
            events.interrupted_target = True

        if state.target_guard_pressure_ratio >= 1.0:
            state.target_guard_pressure_ratio = 0.0
            state.target_blocking = False

        state.target_health_ratio -= damage
        events.damage_dealt = damage

    def _resolve_player_action(self, action: BossAction, events: BossStepEvents) -> None:
        state = self.state
        if not state.target_attacking or state.target_dead:
            return
        if events.successful_dodge:
            return

        damage = self.profile.attack_damage
        if action == BossAction.DEFEND and events.accepted:
            damage *= 0.2
            events.successful_defend = True

        state.boss_health_ratio -= damage
        events.damage_received = damage
        if not events.successful_defend:
            state.boss_poise += self.profile.poise_damage
            if state.boss_poise >= 1.0 and not state.boss_dead:
                state.boss_poise = 0.0
                state.boss_stunned_steps = self.config.stun_duration_steps

    @staticmethod
    def _push_recent_sample(samples: list[float], value: float) -> None:
        samples.append(value)
        if len(samples) > 8:
            del samples[:-8]

    def _track_repetition(self, action: BossAction, events: BossStepEvents) -> None:
        state = self.state
        if state.last_action == action:
            state.consecutive_action_count += 1
        else:
            state.last_action = action
            state.consecutive_action_count = 1
        events.repeat_count = state.consecutive_action_count

    def _advance_action_timers(
        self,
        cooldowns_to_tick: set[BossAction],
        *,
        was_stunned: bool,
    ) -> None:
        for action in cooldowns_to_tick:
            remaining = self.state.cooldown_steps[action] - 1
            if remaining <= 0:
                del self.state.cooldown_steps[action]
            else:
                self.state.cooldown_steps[action] = remaining

        if was_stunned and self.state.boss_stunned_steps > 0:
            self.state.boss_stunned_steps -= 1

    def _terminal_reason(self) -> str | None:
        if self.state.target_dead:
            return "boss_victory"
        if self.state.boss_dead:
            return "boss_defeat"
        if self.state.step >= self.config.max_steps:
            return "timeout"
        return None

    @staticmethod
    def _validate_profile(profile: str) -> str:
        if profile not in PLAYER_PROFILES:
            raise ValueError(f"unknown player profile: {profile}")
        return profile
