"""Train and evaluate the UE-aligned high-level PPO Boss policy."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from rl.boss.contract import BossAction, FEATURE_NAMES, SCHEMA_VERSION
from rl.boss.evaluation import evaluate_policy
from rl.boss.policy import RuleBossPolicy
from rl.boss.rewards import REWARD_REVISION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the UE-aligned PPO Boss")
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-envs", type=int, default=8)
    parser.add_argument("--eval-episodes", type=int, default=50)
    parser.add_argument("--out", type=Path, default=Path("models/rl/boss"))
    parser.add_argument("--name", default="ppo_boss_schema_v3")
    return parser.parse_args()


class PPOBossPolicy:
    def __init__(self, model) -> None:
        self._model = model

    def select_action(self, observation, state) -> BossAction:
        del state
        action, _ = self._model.predict(observation, deterministic=True)
        return BossAction(int(action))


def main() -> None:
    args = parse_args()
    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.env_util import make_vec_env
        from stable_baselines3.common.monitor import Monitor

        from rl.boss.env import AesirBossEnv
    except ImportError as exc:
        raise SystemExit(
            "RL dependencies are missing. Run: "
            ".venv\\Scripts\\python -m pip install -r requirements-rl.txt"
        ) from exc

    if args.timesteps <= 0 or args.n_envs <= 0 or args.eval_episodes <= 0:
        raise SystemExit("timesteps, n-envs, and eval-episodes must be positive")

    args.out.mkdir(parents=True, exist_ok=True)
    model_path = args.out / args.name
    env = make_vec_env(
        AesirBossEnv,
        n_envs=args.n_envs,
        seed=args.seed,
        env_kwargs={"profile": "mixed"},
        wrapper_class=Monitor,
    )
    model = PPO(
        "MlpPolicy",
        env,
        seed=args.seed,
        device="cpu",
        verbose=1,
    )
    model.learn(total_timesteps=args.timesteps, progress_bar=False)
    model.save(str(model_path))

    baseline = evaluate_policy(
        RuleBossPolicy(),
        policy_name="BehaviorTreeRuleBaseline",
        episodes_per_profile=args.eval_episodes,
        base_seed=args.seed,
    )
    ppo = evaluate_policy(
        PPOBossPolicy(model),
        policy_name="PPO",
        episodes_per_profile=args.eval_episodes,
        base_seed=args.seed,
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "feature_names": FEATURE_NAMES,
        "actions": {action.name: action.value for action in BossAction},
        "reward_revision": REWARD_REVISION,
        "seed": args.seed,
        "timesteps": args.timesteps,
        "n_envs": args.n_envs,
        "episodes_per_profile": args.eval_episodes,
        "model": str(model_path.with_suffix(".zip")),
        "baseline": asdict(baseline),
        "ppo": asdict(ppo),
    }
    manifest_path = model_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    env.close()

    print(f"Model: {model_path}.zip")
    print(f"Manifest: {manifest_path}")
    print(
        f"BT win={baseline.boss_win_rate:.3f}, PPO win={ppo.boss_win_rate:.3f}; "
        f"BT reward={baseline.mean_reward:.3f}, PPO reward={ppo.mean_reward:.3f}"
    )


if __name__ == "__main__":
    main()
