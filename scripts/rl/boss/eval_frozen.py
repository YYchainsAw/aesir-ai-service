"""Evaluate the recorded frozen Boss ZIP, without training or HTTP services.

Only load a trusted, locally supplied SB3 ZIP. SHA verification happens before
deserialization. A completed summary is written only after both policies finish.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from rl.boss.contract import ACTION_COUNT, OBSERVATION_DIM, BossAction, make_action_mask
from rl.boss.evaluation import evaluate_policy
from rl.boss.policy import RuleBossPolicy
from scripts.rl.boss.inventory import EXPECTED_SHA256, MODEL_NAME, ROOT, digest


class FrozenBossPolicy:
    def __init__(self, model):
        if tuple(model.observation_space.shape) != (OBSERVATION_DIM,):
            raise ValueError("frozen model observation space does not match schema 4")
        if model.action_space.n != ACTION_COUNT:
            raise ValueError("frozen model action space does not match schema 4")
        self.model = model

    def select_action(self, observation, state) -> BossAction:
        del state
        import numpy as np

        mask = np.asarray(make_action_mask(observation), dtype=np.bool_)
        action, _ = self.model.predict(
            np.asarray(observation, dtype=np.float32),
            deterministic=True, action_masks=mask,
        )
        result = BossAction(int(action))
        if not mask[result]:
            raise ValueError("frozen model selected a masked action")
        return result


def load_frozen_policy(model_path: Path) -> FrozenBossPolicy:
    if digest(model_path) != EXPECTED_SHA256:
        raise ValueError("model SHA-256 does not match the recorded frozen candidate")
    try:
        from sb3_contrib import MaskablePPO
    except ImportError as exc:
        raise ValueError("missing Boss inference dependencies; see requirements-boss-inference.txt") from exc
    return FrozenBossPolicy(MaskablePPO.load(str(model_path), device="cpu"))


def validate_seeds(episodes: int, seed: int) -> None:
    if episodes <= 0 or seed < 0:
        raise ValueError("episodes must be positive and seed must be nonnegative")
    # Recorded selection: 300 episodes/profile starting at 50000.
    if seed < 50300 and seed + episodes > 50000:
        raise ValueError("evaluation seeds overlap recorded selection seeds [50000, 50300)")


def run_evaluation(*, model_path: Path, output: Path, episodes: int, seed: int) -> dict:
    validate_seeds(episodes, seed)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite evaluation evidence: {output}")
    policy = load_frozen_policy(model_path)
    # Leave no output at all if materials or dependencies fail preflight.
    output.mkdir(parents=True, exist_ok=False)
    reports = {}
    raw = output / "episodes.jsonl"
    with raw.open("x", encoding="utf-8") as stream:
        for name, current_policy in (("rule_baseline", RuleBossPolicy()), ("frozen_ppo", policy)):
            def record(episode):
                stream.write(json.dumps({"policy": name, **asdict(episode)}, sort_keys=True) + "\n")
                stream.flush()

            reports[name] = asdict(evaluate_policy(
                current_policy, policy_name=name, episodes_per_profile=episodes,
                base_seed=seed, on_episode=record,
            ))
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    sources = [Path(__file__), *(ROOT / "rl/boss").glob("*.py")]
    software = {}
    for distribution in ("numpy", "torch", "gymnasium", "stable-baselines3", "sb3-contrib"):
        try:
            software[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            software[distribution] = None
    summary = {
        "state": "completed", "scope": "offline_simulator_comparison",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "service_commit": commit,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted(sources)},
        "python_version": platform.python_version(), "platform": platform.platform(),
        "software": software,
        "model_path": str(model_path.resolve()), "model_sha256": EXPECTED_SHA256,
        "deterministic": True, "device": "cpu", "training_performed": False,
        "seed_plan": {"base_seed": seed, "episodes_per_profile": episodes,
                      "strategy": "same_seed_plus_index_for_each_profile_and_policy",
                      "recorded_selection_overlap": False,
                      "training_seed_independence": "not_established"},
        "episodes_sha256": digest(raw), "reports": reports,
        "reproduce_argv": [sys.executable, "-m", "scripts.rl.boss.eval_frozen",
                           "--model", str(model_path.resolve()), "--episodes", str(episodes),
                           "--seed", str(seed), "--output", str(output.resolve()) + "-replay"],
        "ue_acceptance": "not_performed",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path,
                        default=ROOT / "models/rl/boss/deployment" / f"{MODEL_NAME}.zip")
    parser.add_argument("--episodes", type=int, default=100, help="episodes per player profile")
    parser.add_argument("--seed", type=int, default=200000)
    parser.add_argument("--output", type=Path, required=True, help="new evidence directory")
    args = parser.parse_args(argv)
    try:
        summary = run_evaluation(model_path=args.model, output=args.output,
                                 episodes=args.episodes, seed=args.seed)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Frozen evaluation failed: {exc}\n")
    print(json.dumps({"summary": str(args.output / "summary.json"),
                      "state": summary["state"], "model_sha256": summary["model_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
