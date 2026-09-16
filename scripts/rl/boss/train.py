"""Train and evaluate the UE-aligned high-level PPO Boss policy."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from rl.boss.contract import (
    BossAction,
    FEATURE_NAMES,
    SCHEMA_VERSION,
    make_action_mask,
)
from rl.boss.evaluation import evaluate_policy
from rl.boss.policy import RuleBossPolicy
from rl.boss.rewards import REWARD_REVISION, BossRewardWeights
from rl.boss.sim import (
    PLAYER_PROFILES,
    SIMULATION_REVISION,
    BossSimConfig,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the UE-aligned PPO Boss")
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-envs", type=int, default=8)
    parser.add_argument("--n-steps", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--n-epochs", type=int, default=10)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--clip-range", type=float, default=0.2)
    parser.add_argument("--ent-coef", type=float, default=0.0)
    parser.add_argument("--vf-coef", type=float, default=0.5)
    parser.add_argument("--eval-episodes", type=int, default=50)
    parser.add_argument("--checkpoint-freq", type=int, default=100_000)
    parser.add_argument("--periodic-eval-freq", type=int, default=100_000)
    parser.add_argument("--periodic-eval-episodes", type=int, default=30)
    parser.add_argument(
        "--tensorboard-log",
        type=Path,
        default=None,
        help="TensorBoard directory (defaults to <out>/tensorboard)",
    )
    parser.add_argument(
        "--disable-tensorboard",
        action="store_true",
        help="disable event logging for dependency-light smoke tests",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="continue training from an existing MaskablePPO .zip checkpoint",
    )
    parser.add_argument("--out", type=Path, default=Path("models/rl/boss"))
    parser.add_argument("--name", default="ppo_boss_schema_v4")
    return parser.parse_args()


class PPOBossPolicy:
    def __init__(self, model) -> None:
        self._model = model

    def select_action(self, observation, state) -> BossAction:
        del state
        action_mask = np.asarray(make_action_mask(observation), dtype=np.bool_)
        action, _ = self._model.predict(
            observation,
            deterministic=True,
            action_masks=action_mask,
        )
        return BossAction(int(action))


def main() -> None:
    args = parse_args()
    try:
        from sb3_contrib import MaskablePPO
        from sb3_contrib.common.maskable.callbacks import MaskableEvalCallback
        from stable_baselines3.common.callbacks import CheckpointCallback
        from stable_baselines3.common.env_util import make_vec_env
        from stable_baselines3.common.monitor import Monitor

        from rl.boss.env import AesirBossEnv, EPISODE_SEED_STRATEGY
    except ImportError as exc:
        raise SystemExit(
            "RL dependencies are missing. Run: "
            ".venv\\Scripts\\python -m pip install -r requirements-rl.txt"
        ) from exc

    if not args.disable_tensorboard:
        try:
            version("tensorboard")
        except PackageNotFoundError as exc:
            raise SystemExit(
                "TensorBoard is missing. Run: "
                ".venv\\Scripts\\python -m pip install -r requirements-rl.txt "
                "or use --disable-tensorboard only for a smoke test."
            ) from exc

    positive_values = (
        args.timesteps,
        args.n_envs,
        args.n_steps,
        args.batch_size,
        args.n_epochs,
        args.eval_episodes,
        args.checkpoint_freq,
        args.periodic_eval_freq,
        args.periodic_eval_episodes,
    )
    if any(value <= 0 for value in positive_values):
        raise SystemExit("training, checkpoint, and evaluation values must be positive")
    if args.batch_size > args.n_steps * args.n_envs:
        raise SystemExit("batch-size cannot exceed n-steps * n-envs")
    if not 0.0 < args.gamma <= 1.0 or not 0.0 < args.gae_lambda <= 1.0:
        raise SystemExit("gamma and gae-lambda must be in (0, 1]")
    if args.learning_rate <= 0.0 or args.clip_range <= 0.0:
        raise SystemExit("learning-rate and clip-range must be positive")
    if args.resume is not None and not args.resume.exists():
        raise SystemExit(f"resume checkpoint does not exist: {args.resume}")

    args.out.mkdir(parents=True, exist_ok=True)
    model_path = args.out / args.name
    checkpoint_dir = args.out / "checkpoints" / args.name
    best_model_dir = args.out / "best" / args.name
    periodic_eval_dir = args.out / "evaluations" / args.name
    tensorboard_dir = args.tensorboard_log or args.out / "tensorboard"
    for directory in (
        checkpoint_dir,
        best_model_dir,
        periodic_eval_dir,
        tensorboard_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    env = make_vec_env(
        AesirBossEnv,
        n_envs=args.n_envs,
        seed=args.seed,
        env_kwargs={"profile": "mixed"},
        wrapper_class=Monitor,
    )
    tensorboard_log = None if args.disable_tensorboard else str(tensorboard_dir)
    if args.resume is None:
        model = MaskablePPO(
            "MlpPolicy",
            env,
            seed=args.seed,
            device="cpu",
            verbose=1,
            tensorboard_log=tensorboard_log,
            n_steps=args.n_steps,
            batch_size=args.batch_size,
            n_epochs=args.n_epochs,
            learning_rate=args.learning_rate,
            gamma=args.gamma,
            gae_lambda=args.gae_lambda,
            clip_range=args.clip_range,
            ent_coef=args.ent_coef,
            vf_coef=args.vf_coef,
        )
    else:
        model = MaskablePPO.load(
            str(args.resume),
            env=env,
            device="cpu",
            tensorboard_log=tensorboard_log,
        )
    eval_env = Monitor(
        AesirBossEnv(seed=args.seed + 100_000, profile="mixed")
    )
    eval_env.reset(seed=args.seed + 100_000)
    checkpoint_callback = CheckpointCallback(
        save_freq=max(args.checkpoint_freq // args.n_envs, 1),
        save_path=str(checkpoint_dir),
        name_prefix=args.name,
    )
    eval_callback = MaskableEvalCallback(
        eval_env,
        best_model_save_path=str(best_model_dir),
        log_path=str(periodic_eval_dir),
        eval_freq=max(args.periodic_eval_freq // args.n_envs, 1),
        n_eval_episodes=args.periodic_eval_episodes,
        deterministic=True,
        warn=False,
    )
    model.learn(
        total_timesteps=args.timesteps,
        callback=[checkpoint_callback, eval_callback],
        progress_bar=False,
        tb_log_name=args.name,
        reset_num_timesteps=args.resume is None,
    )
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
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "simulation_revision": SIMULATION_REVISION,
        "episode_seed_strategy": EPISODE_SEED_STRATEGY,
        "simulation_config": asdict(BossSimConfig()),
        "player_profiles": {
            name: asdict(profile) for name, profile in PLAYER_PROFILES.items()
        },
        "feature_names": FEATURE_NAMES,
        "actions": {action.name: action.value for action in BossAction},
        "reward_revision": REWARD_REVISION,
        "reward_weights": asdict(BossRewardWeights()),
        "seed": args.seed,
        "training_timesteps_requested_this_run": args.timesteps,
        "total_timesteps": model.num_timesteps,
        "n_envs": args.n_envs,
        "resumed_from": str(args.resume) if args.resume is not None else None,
        "hyperparameters": {
            "n_steps": model.n_steps,
            "batch_size": model.batch_size,
            "n_epochs": model.n_epochs,
            "learning_rate_initial": float(model.lr_schedule(1.0)),
            "gamma": model.gamma,
            "gae_lambda": model.gae_lambda,
            "clip_range_initial": float(model.clip_range(1.0)),
            "ent_coef": model.ent_coef,
            "vf_coef": model.vf_coef,
        },
        "episodes_per_profile": args.eval_episodes,
        "model": str(model_path.with_suffix(".zip")),
        "artifacts": {
            "tensorboard_root": (
                None if args.disable_tensorboard else str(tensorboard_dir)
            ),
            "checkpoints": str(checkpoint_dir),
            "best_model": str(best_model_dir / "best_model.zip"),
            "periodic_evaluations": str(periodic_eval_dir / "evaluations.npz"),
        },
        "checkpoint_frequency_timesteps": args.checkpoint_freq,
        "periodic_eval_frequency_timesteps": args.periodic_eval_freq,
        "periodic_eval_episodes": args.periodic_eval_episodes,
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "gymnasium": _package_version("gymnasium"),
            "stable_baselines3": _package_version("stable-baselines3"),
            "sb3_contrib": _package_version("sb3-contrib"),
            "torch": _package_version("torch"),
            "tensorboard": (
                None if args.disable_tensorboard else _package_version("tensorboard")
            ),
        },
        "baseline": asdict(baseline),
        "ppo": asdict(ppo),
    }
    manifest_path = model_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    env.close()
    eval_env.close()

    print(f"Model: {model_path}.zip")
    print(f"Manifest: {manifest_path}")
    print(
        "TensorBoard: "
        + ("disabled" if args.disable_tensorboard else str(tensorboard_dir))
    )
    print(f"Checkpoints: {checkpoint_dir}")
    print(f"Best periodic model: {best_model_dir / 'best_model.zip'}")
    print(
        f"BT win={baseline.boss_win_rate:.3f}, PPO win={ppo.boss_win_rate:.3f}; "
        f"BT reward={baseline.mean_reward:.3f}, PPO reward={ppo.mean_reward:.3f}"
    )


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "not-installed"


if __name__ == "__main__":
    main()
