"""A/B 评测脚本：规则基线 vs 训练后的 PPO 模型（L3；--agents rule 时无需 sb3）。

用法：
    .\\.venv\\Scripts\\python scripts\\rl_eval.py --episodes 50 --agents rule
    .\\.venv\\Scripts\\python scripts\\rl_eval.py --episodes 100 --agents rule,models/rl/ppo_bossfight

输出对齐 scripts/asr_eval.py：逐 agent 汇总 markdown 表。核心盯防指标：
stun_burst_rate（眩晕窗口 explosion 施放率）+ win_rate 联合判定（防 reward
hacking，见 docs/RL可行性分析与框架设计.md §8）。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rl.eval_utils import evaluate_policy
from rl.policy.rule import RulePolicyAdapter
from rl.sim.core import BossSim


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A/B 评测：规则基线 vs PPO 模型")
    p.add_argument("--episodes", type=int, default=50, help="每个 agent 的评测局数")
    p.add_argument("--agents", type=str, default="rule",
                   help="逗号分隔：rule 或模型路径（.zip 可省略后缀）")
    p.add_argument("--seed", type=int, default=0, help="起始种子（各 agent 用同一序列保证可比）")
    return p.parse_args()


def _load_policy(spec: str):
    if spec == "rule":
        return RulePolicyAdapter(), "rule"
    try:
        from stable_baselines3 import PPO
    except ImportError as exc:
        raise SystemExit(
            f"agent '{spec}' 需要 stable-baselines3：.venv\\Scripts\\python -m pip install -r requirements-rl.txt"
        ) from exc
    path = spec
    model = PPO.load(path, device="cpu")  # 缺 .zip 后缀时 sb3 自动补
    return _PPOPolicyAdapter(model), f"ppo({spec})"


class _PPOPolicyAdapter:
    """sb3 模型 → ActingPolicy 适配器（ ActingPolicy 协议的 PPO 侧实现）。"""

    def __init__(self, model):
        self._model = model

    def select_action(self, obs, state) -> int:
        action, _ = self._model.predict(obs, deterministic=True)
        return int(action)


def main() -> None:
    args = parse_args()
    specs = [s.strip() for s in args.agents.split(",") if s.strip()]
    sim = BossSim(seed=args.seed)

    rows = []
    for spec in specs:
        policy, label = _load_policy(spec)
        report = evaluate_policy(sim, policy, episodes=args.episodes, base_seed=args.seed)
        rows.append((label, report))

    print(f"\nA/B 评测（{args.episodes} 局/agent，种子 {args.seed} 起）\n")
    print("| agent | mean_reward | win_rate | player_survival | mean_ticks | stun_burst_rate | 终局分布 |")
    print("|---|---|---|---|---|---|---|")
    for label, r in rows:
        reasons = ", ".join(f"{k}:{v}" for k, v in sorted(r.reasons.items()))
        print(
            f"| {label} | {r.mean_reward:.2f} | {r.win_rate:.2f} | {r.player_survival_rate:.2f} "
            f"| {r.mean_ticks:.1f} | {r.explosion_in_stun_rate:.2f} | {reasons} |"
        )
    print("\n判定标准：RL 的 win_rate 不低于规则基线且 stun_burst_rate 显著更高时，才考虑上线（§8）。")


if __name__ == "__main__":
    main()
