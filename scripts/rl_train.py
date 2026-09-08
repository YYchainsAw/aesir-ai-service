"""PPO 训练脚本：AliceBossEnv 上训练 MLP 策略（L3，依赖 sb3 + torch）。

用法（风格对齐 scripts/asr_eval.py）：
    .\\.venv\\Scripts\\python scripts\\rl_train.py --timesteps 20000           # 冒烟（~1-2 分钟）
    .\\.venv\\Scripts\\python scripts\\rl_train.py --timesteps 1000000 --seed 7 # 正式

默认 device=cpu：MLP 策略 GPU 收益极小，且避免与 faster-whisper 抢 8GB 显存。
"""

import argparse
from pathlib import Path

from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.monitor import Monitor

from rl.env import AliceBossEnv
from rl.eval_utils import evaluate_policy
from rl.policy.ppo import PPOPolicyAdapter
from rl.policy.rule import RulePolicyAdapter
from rl.sim.core import BossSim


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PPO 训练：Boss 战模拟器")
    p.add_argument("--timesteps", type=int, default=1_000_000, help="总训练步数")
    p.add_argument("--seed", type=int, default=0, help="随机种子")
    p.add_argument("--n-envs", type=int, default=8, help="并行环境数")
    p.add_argument("--out", type=str, default="models/rl", help="模型保存目录")
    p.add_argument("--name", type=str, default="ppo_bossfight", help="模型文件名")
    p.add_argument("--eval-every", type=int, default=100_000, help="每 N 步打印一次规则基线对照分")
    p.add_argument("--eval-episodes", type=int, default=20, help="对照评测局数")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / args.name

    env = make_vec_env(AliceBossEnv, n_envs=args.n_envs, seed=args.seed, wrapper_class=Monitor)

    model = PPO(
        "MlpPolicy",
        env,
        seed=args.seed,
        device="cpu",
        verbose=0,
    )

    # 规则基线是确定性的、训练期间不变：只测一次作为对照锚点。
    baseline = evaluate_policy(BossSim(seed=args.seed), RulePolicyAdapter(), episodes=args.eval_episodes)
    print(
        f"规则基线：mean_reward={baseline.mean_reward:.2f} win_rate={baseline.win_rate:.2f} "
        f"mean_ticks={baseline.mean_ticks:.1f} stun_burst_rate={baseline.explosion_in_stun_rate:.2f}"
    )

    # 分段 learn：每段之间评测当前 PPO（训练期进度可见；正式 A/B 用 scripts/rl_eval.py）

    remaining = args.timesteps
    done_steps = 0
    while remaining > 0:
        chunk = min(remaining, args.eval_every)
        model.learn(total_timesteps=chunk, reset_num_timesteps=False, progress_bar=False)
        done_steps += chunk
        remaining -= chunk
        report = evaluate_policy(
            BossSim(seed=args.seed), PPOPolicyAdapter(model), episodes=args.eval_episodes
        )
        print(
            f"[{done_steps}/{args.timesteps}] PPO 进度："
            f"mean_reward={report.mean_reward:.2f} (基线 {baseline.mean_reward:.2f}) "
            f"win_rate={report.win_rate:.2f} stun_burst_rate={report.explosion_in_stun_rate:.2f}"
        )

    model.save(str(model_path))
    print(f"模型已保存：{model_path}.zip")


if __name__ == "__main__":
    main()
