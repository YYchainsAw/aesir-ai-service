"""观测特征测试（依赖 numpy，缺失自动 skip）。"""

import pytest

pytest.importorskip("numpy")

import numpy as np  # noqa: E402

from app.schemas.combat_context import make_combat_context  # noqa: E402
from rl.features import OBS_DIM, extract_observation, extract_observation_from_state  # noqa: E402


def test_obs_dim_and_range() -> None:
    ctx = make_combat_context(player_hp=50)
    obs = extract_observation(ctx, tick=10)
    assert obs.shape == (OBS_DIM,)
    assert obs.dtype == np.float32
    assert (obs >= 0.0).all() and (obs <= 1.0).all()


def test_obs_reflects_context_changes() -> None:
    ctx = make_combat_context(player_hp=20, boss_state_tags=["state.stunned"], stunned_remaining=5.0)
    obs = extract_observation(ctx)
    assert obs[0] == pytest.approx(0.2)          # player_hp
    assert obs[3] == pytest.approx(1.0)          # stun_percent=100
    assert obs[5] == pytest.approx(0.5)          # stunned_remaining 5s / 10s


def test_ability_ready_flags() -> None:
    ctx = make_combat_context(player_hp=50)
    ctx.companion.ability_states["ability.alice.explosion"] = "cooldown"
    obs = extract_observation(ctx)
    assert obs[9] == 0.0  # explosion not ready（_ABILITY_ORDER 第 2 个）
    assert obs[8] == 1.0  # basic_attack ready


def test_from_state_sim_integration() -> None:
    from rl.sim.core import BossSim

    sim = BossSim(seed=0)
    obs = extract_observation_from_state(sim.state)
    assert obs.shape == (OBS_DIM,)
    assert obs[0] == pytest.approx(1.0)  # 满血开局


def test_flags_and_tick_normalization() -> None:
    ctx = make_combat_context(player_hp=50)
    obs = extract_observation(ctx, shield_active=True, retreat_active=True, tick=150, max_ticks=300)
    assert obs[13] == 1.0 and obs[14] == 1.0
    assert obs[15] == pytest.approx(0.5)
