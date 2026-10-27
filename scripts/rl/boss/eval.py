"""Evaluate rule/frozen policies without training; preserve reproducible evidence."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from rl.boss.contract import BossAction, FEATURE_NAMES, SCHEMA_VERSION
from rl.boss.evaluation import (
    DEFAULT_HOLDOUT_SEED,
    SELECTION_SEED_FIRST,
    SELECTION_SEED_LAST,
    FrozenBossPolicy,
    evaluate_policy,
    validate_holdout_seeds,
)
from rl.boss.policy import RuleBossPolicy
from rl.boss.rewards import REWARD_REVISION, BossRewardWeights
from rl.boss.sim import PLAYER_PROFILES, SIMULATION_REVISION, BossSimConfig


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=("rule", "frozen", "compare"), default="rule")
    parser.add_argument("--model", type=Path, help="reviewed frozen .zip and its sidecars")
    parser.add_argument("--episodes", type=int, default=20, help="episodes per profile per policy")
    parser.add_argument("--seed", type=int, default=None, help="first seed (rule: 0; frozen/compare: 200000)")
    parser.add_argument("--out", type=Path, help="new evidence directory; required for frozen/compare")
    parser.add_argument("--json", action="store_true", help="emit machine-readable summary")
    args = parser.parse_args(argv)
    if args.episodes <= 0:
        parser.error("--episodes must be positive")
    if args.seed is None:
        args.seed = 0 if args.policy == "rule" else DEFAULT_HOLDOUT_SEED
    if args.seed < 0:
        parser.error("--seed must be nonnegative")
    if args.policy != "rule":
        if args.model is None or args.out is None:
            parser.error("--model and --out are required for frozen/compare")
        try:
            validate_holdout_seeds(args.seed, args.episodes)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.model is not None:
        parser.error("--model applies only to frozen/compare")
    if args.out is not None and args.out.exists():
        parser.error("--out already exists; evidence is never overwritten")
    return args


def _json(value, *, indent=None) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent, allow_nan=False)


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _git(*arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), *arguments],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def source_provenance() -> dict:
    paths = (
        "rl/boss/contract.py", "rl/boss/evaluation.py", "rl/boss/inference.py",
        "rl/boss/release.py", "rl/boss/deployment.json", "rl/boss/policy.py",
        "rl/boss/rewards.py", "rl/boss/sim.py", "scripts/rl/boss/eval.py",
    )
    return {
        "repository_commit": _git("rev-parse", "HEAD"),
        "tracked_worktree_changes": _git("status", "--porcelain", "--untracked-files=no"),
        "source_sha256": {
            name: sha256((REPOSITORY_ROOT / name).read_bytes()).hexdigest()
            for name in paths if (REPOSITORY_ROOT / name).is_file()
        },
    }


def _paired_comparison(records: dict[str, list[dict]]) -> dict:
    if "rule" not in records or "frozen" not in records:
        return {}
    indexed = {
        name: {(row["player_profile"], row["seed"]): row for row in rows}
        for name, rows in records.items()
    }
    if indexed["rule"].keys() != indexed["frozen"].keys():
        raise ValueError("paired policies do not share the same profile/seed cases")
    profiles = {}
    for profile in PLAYER_PROFILES:
        pairs = [
            (rule, indexed["frozen"][key])
            for key, rule in indexed["rule"].items() if key[0] == profile
        ]
        profiles[profile] = {
            "pairs": len(pairs),
            "frozen_only_boss_victories": sum(f["result"] == "boss_victory" and r["result"] != "boss_victory" for r, f in pairs),
            "rule_only_boss_victories": sum(r["result"] == "boss_victory" and f["result"] != "boss_victory" for r, f in pairs),
            "both_boss_victories": sum(r["result"] == f["result"] == "boss_victory" for r, f in pairs),
            "mean_reward_delta_frozen_minus_rule": statistics.fmean(f["total_reward"] - r["total_reward"] for r, f in pairs),
            "mean_damage_dealt_delta_frozen_minus_rule": statistics.fmean(f["damage_dealt"] - r["damage_dealt"] for r, f in pairs),
            "boss_win_rate_delta_frozen_minus_rule": statistics.fmean(int(f["result"] == "boss_victory") - int(r["result"] == "boss_victory") for r, f in pairs),
        }
    return profiles


def _archive_frozen_materials(frozen: FrozenBossPolicy, output: Path) -> dict:
    from rl.boss.release import load_release_descriptor

    descriptor = load_release_descriptor()
    artifacts = {}
    for material in ("selection", "training"):
        source = frozen.runtime.model_path.with_name(str(descriptor[f"{material}_file"]))
        data = source.read_bytes()
        digest = sha256(data).hexdigest()
        if digest != frozen.runtime.provenance[f"{material}_sha256"]:
            raise ValueError(f"frozen {material} material changed after validation")
        artifact_name = f"frozen-{material}.json"
        with (output / artifact_name).open("xb") as target:
            target.write(data)
        artifacts[artifact_name] = {"sha256": digest, "source_name": source.name}
    return artifacts


def run_experiment(args: argparse.Namespace) -> dict:
    # Validate/load the reviewed bytes before allocating an output directory.
    frozen = FrozenBossPolicy.from_model(args.model) if args.policy != "rule" else None
    policies = {}
    if args.policy in ("rule", "compare"):
        policies["rule"] = (RuleBossPolicy(), "SimulatorRuleBaseline")
    if frozen is not None:
        policies["frozen"] = (frozen, "FrozenMaskablePPO")
    output = args.out
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
    material_artifacts = _archive_frozen_materials(frozen, output) if frozen is not None else {}
    records: dict[str, list[dict]] = {}
    reports = {}
    episode_file = (output / "episodes.jsonl").open("x", encoding="utf-8", newline="\n") if output is not None else None
    try:
        for name, (policy, display_name) in policies.items():
            records[name] = []

            def record(episode, policy_key=name):
                row = {"policy": policy_key, **asdict(episode)}
                encoded = _json(row)
                records[policy_key].append(row)
                if episode_file is not None:
                    episode_file.write(encoded + "\n")
                    episode_file.flush()

            report = evaluate_policy(
                policy, policy_name=display_name, episodes_per_profile=args.episodes,
                base_seed=args.seed, episode_sink=record,
            )
            reports[name] = asdict(report)
    finally:
        if episode_file is not None:
            episode_file.close()
    summary = {
        "scope": "Python simulator only; the rule baseline is not measured UE Behavior Tree performance",
        "episodes_per_profile_per_policy": args.episodes,
        "profiles": list(PLAYER_PROFILES),
        "episodes_per_policy": args.episodes * len(PLAYER_PROFILES),
        "total_episode_records": sum(len(rows) for rows in records.values()),
        "reports": reports,
        "paired_comparison_by_profile": _paired_comparison(records),
    }
    if output is not None:
        (output / "summary.json").write_text(_json(summary, indent=2) + "\n", encoding="utf-8")
        manifest = {
            "experiment_type": "post_freeze_simulator_holdout" if frozen else "simulator_rule_evaluation",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "policy_mode": args.policy,
            "schema_version": SCHEMA_VERSION,
            "simulation_revision": SIMULATION_REVISION,
            "reward_revision": REWARD_REVISION,
            "feature_names": FEATURE_NAMES,
            "actions": {action.name: int(action) for action in BossAction},
            "simulation_config": asdict(BossSimConfig()),
            "player_profiles": {name: asdict(value) for name, value in PLAYER_PROFILES.items()},
            "reward_weights": asdict(BossRewardWeights()),
            "seed_protocol": {
                "strategy": "fixed_profile_and_identical_seed_range_per_policy_v1",
                "first_inclusive": args.seed,
                "last_inclusive": args.seed + args.episodes - 1,
                "episodes_per_profile_per_policy": args.episodes,
                "excluded_candidate_selection_seed_range": [SELECTION_SEED_FIRST, SELECTION_SEED_LAST] if frozen else None,
                "training_seed_independence": "not proven: training automatic resets draw from a broad RNG domain",
                "pairing_limit": "same initial profile/seed; action-dependent RNG consumption can diverge between policies",
                "candidate_retrained_or_reselected": False,
            },
            "model": None if frozen is None else {
                "path": str(frozen.runtime.model_path.resolve()),
                "verified_provenance": frozen.runtime.provenance,
            },
            "source": source_provenance(),
            "software": {
                "python": platform.python_version(), "platform": platform.platform(),
                **{name: _package_version(name) for name in ("numpy", "gymnasium", "stable-baselines3", "sb3-contrib", "torch")},
            },
            "artifacts": {
                **material_artifacts,
                **{
                name: {"sha256": sha256((output / name).read_bytes()).hexdigest()}
                for name in ("episodes.jsonl", "summary.json")
                },
            },
            "limitations": [summary["scope"], "No UE integration, gameplay quality or release acceptance is established by this simulator experiment."],
        }
        (output / "manifest.json").write_text(_json(manifest, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None) -> None:
    args = parse_args(argv)
    summary = run_experiment(args)
    if args.json:
        # Preserve the historical rule-only JSON report for existing callers.
        payload = summary["reports"]["rule"] if args.policy == "rule" else summary
        print(_json(payload, indent=2))
        return
    print(summary["scope"])
    for name, report in summary["reports"].items():
        print(f"{name}: episodes={report['episodes']} win={report['boss_win_rate']:.3f} ci95=[{report['boss_win_rate_ci95_low']:.3f}, {report['boss_win_rate_ci95_high']:.3f}] reward={report['mean_reward']:.3f}")
        for profile, metrics in report["metrics_by_profile"].items():
            print(f"  {profile}: episodes={metrics['episodes']} win={metrics['boss_win_rate']:.3f} reward={metrics['mean_reward']:.3f} rejected={metrics['rejected_action_rate']:.3f} locked={metrics['state_locked_rate']:.3f}")
    if args.out is not None:
        print(f"Evidence: {args.out.resolve()}")


if __name__ == "__main__":
    main()
