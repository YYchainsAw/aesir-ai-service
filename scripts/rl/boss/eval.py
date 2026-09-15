"""Evaluate the UE-aligned rule Boss baseline without RL dependencies."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from rl.boss.evaluation import evaluate_policy
from rl.boss.policy import RuleBossPolicy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the rule Boss baseline")
    parser.add_argument("--episodes", type=int, default=20, help="episodes per profile")
    parser.add_argument("--seed", type=int, default=0, help="first reproducible seed")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = evaluate_policy(
        RuleBossPolicy(),
        policy_name="BehaviorTreeRuleBaseline",
        episodes_per_profile=args.episodes,
        base_seed=args.seed,
    )
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
        return

    print(
        f"Boss baseline: schema=v{report.schema_version} "
        f"reward={report.reward_revision} episodes={report.episodes}"
    )
    print(
        f"win={report.boss_win_rate:.3f} defeat={report.boss_defeat_rate:.3f} "
        f"timeout={report.timeout_rate:.3f} decisions={report.mean_decisions:.1f}"
    )
    print(
        f"reward={report.mean_reward:.3f} dealt={report.mean_damage_dealt:.3f} "
        f"received={report.mean_damage_received:.3f} "
        f"rejected={report.rejected_action_rate:.3f} "
        f"state_locked={report.state_locked_rate:.3f} "
        f"repeated={report.repeated_action_rate:.3f}"
    )
    print(f"actions={report.action_distribution}")
    print(f"profiles={report.results_by_profile}")


if __name__ == "__main__":
    main()
