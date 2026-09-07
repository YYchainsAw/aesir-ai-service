"""AliceBossEnv 环境测试（依赖 gymnasium + numpy，缺失自动 skip）。"""

import pytest

pytest.importorskip("gymnasium")
pytest.importorskip("numpy")

import numpy as np  # noqa: E402
from gymnasium.utils.env_checker import check_env  # noqa: E402

from rl.env import AliceBossEnv  # noqa: E402
from rl.features import OBS_DIM  # noqa: E402


def test_env_passes_gymnasium_checker() -> None:
    check_env(AliceBossEnv(seed=0), skip_render_check=True)


def test_reset_returns_valid_obs() -> None:
    env = AliceBossEnv(seed=1)
    obs, info = env.reset(seed=1)
    assert obs.shape == (OBS_DIM,)
    assert obs.dtype == np.float32
    assert env.observation_space.contains(obs)


def test_step_shapes_and_flags() -> None:
    env = AliceBossEnv(seed=2)
    env.reset(seed=2)
    obs, reward, terminated, truncated, info = env.step(1)  # basic_attack
    assert obs.shape == (OBS_DIM,)
    assert isinstance(reward, float)
    assert not (terminated and truncated)
    assert info["done_reason"] in (None, "boss_dead", "player_downed", "companion_downed", "timeout")


def test_same_seed_reproducible() -> None:
    traj1, traj2 = [], []
    for trajs in (traj1, traj2):
        env = AliceBossEnv(seed=5)
        env.reset(seed=5)
        for _ in range(60):
            obs, reward, terminated, truncated, _ = env.step(1)
            trajs.append((obs.copy(), reward))
            if terminated or truncated:
                break
    assert len(traj1) == len(traj2)
    for (o1, r1), (o2, r2) in zip(traj1, traj2):
        assert np.array_equal(o1, o2)
        assert r1 == r2
