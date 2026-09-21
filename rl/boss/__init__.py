"""RL Boss policy environment aligned with Unreal observation schema v4."""

from rl.boss.contract import BossAction, FEATURE_NAMES, OBSERVATION_DIM, SCHEMA_VERSION

__all__ = [
    "BossAction",
    "FEATURE_NAMES",
    "OBSERVATION_DIM",
    "SCHEMA_VERSION",
]
