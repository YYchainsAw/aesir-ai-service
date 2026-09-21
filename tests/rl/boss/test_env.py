"""Contract and Gymnasium checks for the UE-aligned Boss policy."""

import pytest

pytest.importorskip("gymnasium")
pytest.importorskip("numpy")

import numpy as np  # noqa: E402
from gymnasium.utils.env_checker import check_env  # noqa: E402

from rl.boss.contract import (  # noqa: E402
    BossAction,
    FEATURE_NAMES,
    OBSERVATION_DIM,
    SCHEMA_VERSION,
)
from rl.boss.env import AesirBossEnv  # noqa: E402


def test_contract_matches_unreal_schema_v4() -> None:
    assert SCHEMA_VERSION == 4
    assert OBSERVATION_DIM == 26
    assert FEATURE_NAMES[0] == "boss_health_ratio"
    assert FEATURE_NAMES[-1] == "unblockable_area_skill_available"
    assert [action.value for action in BossAction] == list(range(9))
    assert BossAction.PURSUE.value == 4
    assert BossAction.USE_ABILITY.value == 6


def test_env_passes_gymnasium_checker() -> None:
    check_env(AesirBossEnv(seed=0, profile="aggressive"), skip_render_check=True)


def test_observation_and_reward_terms_are_explicit() -> None:
    env = AesirBossEnv(seed=3, profile="defensive")
    observation, reset_info = env.reset(seed=3)
    assert observation.shape == (OBSERVATION_DIM,)
    assert observation.dtype == np.float32
    assert env.observation_space.contains(observation)
    assert reset_info["player_profile"] == "defensive"
    assert env.action_masks().shape == (len(BossAction),)
    assert env.action_masks().dtype == np.bool_

    _, reward, terminated, truncated, info = env.step(BossAction.PURSUE)
    assert isinstance(reward, float)
    assert not (terminated and truncated)
    assert info["schema_version"] == SCHEMA_VERSION
    assert info["simulation_revision"] == "boss-sim-005"
    assert info["episode_seed"] == 3
    assert info["episode_seed_strategy"] == "gym_rng_per_episode_v1"
    assert info["accepted"] is True
    assert "decision_step" in info["reward_terms"]


def test_same_seed_and_profile_are_reproducible() -> None:
    actions = [4, 4, 1, 3, 0, 2, 5, 4, 6] * 5
    trajectories = []
    for _ in range(2):
        env = AesirBossEnv(seed=11, profile="evasive")
        observation, _ = env.reset(seed=11)
        trajectory = [observation.copy()]
        for action in actions:
            observation, reward, terminated, truncated, _ = env.step(action)
            trajectory.append((observation.copy(), reward))
            if terminated or truncated:
                break
        trajectories.append(trajectory)

    assert len(trajectories[0]) == len(trajectories[1])
    for first, second in zip(trajectories[0], trajectories[1]):
        if isinstance(first, np.ndarray):
            assert np.array_equal(first, second)
        else:
            assert np.array_equal(first[0], second[0])
            assert first[1] == second[1]


def test_automatic_resets_use_new_reproducible_episode_seeds() -> None:
    seed_sequences = []
    for _ in range(2):
        env = AesirBossEnv(seed=23, profile="aggressive")
        _, first_info = env.reset(seed=23)
        _, second_info = env.reset()
        _, third_info = env.reset()
        seed_sequences.append(
            (
                first_info["episode_seed"],
                second_info["episode_seed"],
                third_info["episode_seed"],
            )
        )

    assert seed_sequences[0] == seed_sequences[1]
    assert len(set(seed_sequences[0])) == len(seed_sequences[0])


def test_invalid_action_receives_penalty() -> None:
    env = AesirBossEnv(seed=7, profile="aggressive")
    env.reset(seed=7)
    env.unwrapped_sim.state.normalized_distance = 0.05
    _, _, _, _, info = env.step(BossAction.PURSUE)
    assert info["accepted"] is False
    assert info["reward_terms"]["invalid_action"] < 0.0
