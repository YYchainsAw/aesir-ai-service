"""Stable contract shared by Boss training and Unreal runtime inference.

Do not reorder these values without increasing ``SCHEMA_VERSION`` and
retraining every model. The integer action values mirror
``EAesirBossAction`` in Unreal.
"""

from enum import IntEnum
from typing import Iterable

SCHEMA_VERSION = 3

FEATURE_NAMES = (
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
    "light_attack_available",
    "heavy_attack_available",
    "defend_available",
    "dodge_available",
    "pursue_available",
    "disengage_available",
    "use_ability_available",
)
OBSERVATION_DIM = len(FEATURE_NAMES)

OBSERVATION_LOW = (0.0,) * OBSERVATION_DIM
OBSERVATION_HIGH = (1.0,) * OBSERVATION_DIM


class BossAction(IntEnum):
    LIGHT_ATTACK = 0
    HEAVY_ATTACK = 1
    DEFEND = 2
    DODGE = 3
    PURSUE = 4
    DISENGAGE = 5
    USE_ABILITY = 6


ACTION_COUNT = len(BossAction)


def make_observation(values: Iterable[float]) -> tuple[float, ...]:
    """Build and validate one schema-v3 observation."""
    observation = tuple(float(value) for value in values)
    if len(observation) != OBSERVATION_DIM:
        raise ValueError(
            f"schema v{SCHEMA_VERSION} expects {OBSERVATION_DIM} features, "
            f"received {len(observation)}"
        )
    if any(
        value < low or value > high
        for value, low, high in zip(observation, OBSERVATION_LOW, OBSERVATION_HIGH)
    ):
        raise ValueError("observation contains values outside the schema-v3 bounds")
    return observation
