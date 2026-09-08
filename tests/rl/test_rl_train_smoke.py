"""训练冒烟测试（重依赖：sb3 + torch；沿用 AESIR_ASR_SMOKE 门控先例）。

运行：$env:AESIR_RL_SMOKE = "1" 后
    python -m pytest tests/test_rl_train_smoke.py -q
"""

import os
import sys
from pathlib import Path

import pytest

requires_rl = pytest.mark.skipif(
    os.environ.get("AESIR_RL_SMOKE") != "1", reason="设置 AESIR_RL_SMOKE=1 启用训练冒烟"
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@requires_rl
def test_train_save_and_eval_smoke(tmp_path) -> None:
    pytest.importorskip("stable_baselines3")
    pytest.importorskip("torch")

    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.monitor import Monitor

    from rl.env import AliceBossEnv
    from rl.eval_utils import evaluate_policy
    from rl.policy.rule import RulePolicyAdapter
    from rl.sim.core import BossSim

    env = make_vec_env(AliceBossEnv, n_envs=2, seed=0, wrapper_class=Monitor)
    model = PPO("MlpPolicy", env, seed=0, device="cpu", verbose=0)
    model.learn(total_timesteps=2000)
    model_path = tmp_path / "smoke_model"
    model.save(str(model_path))
    assert Path(str(model_path) + ".zip").exists()

    # 规则基线与 PPO 模型各跑 5 局，验证 eval 链路不崩
    rule_report = evaluate_policy(BossSim(seed=0), RulePolicyAdapter(), episodes=5)
    assert rule_report.episodes == 5

    from rl.policy.ppo import PPOPolicyAdapter

    ppo_model = PPO.load(str(model_path), device="cpu")
    ppo_report = evaluate_policy(BossSim(seed=0), PPOPolicyAdapter(ppo_model), episodes=5)
    assert ppo_report.episodes == 5
