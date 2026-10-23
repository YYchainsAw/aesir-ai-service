"""Simulator evidence protocol tests; no model loading or RL extras required."""

from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rl.boss.contract import BossAction
from rl.boss.evaluation import (
    DEFAULT_HOLDOUT_SEED,
    FrozenBossPolicy,
    evaluate_policy,
    run_episode,
    validate_holdout_seeds,
)
from rl.boss.policy import RuleBossPolicy
from rl.boss.sim import PLAYER_PROFILES, BossPolicySim
from scripts.rl.boss import eval as evaluator


def test_existing_evaluate_policy_structure_and_case_counts_are_preserved():
    episodes = []
    report = evaluate_policy(RuleBossPolicy(), policy_name="Rule", episodes_per_profile=2, base_seed=100, episode_sink=episodes.append)
    assert report.episodes == 2 * len(PLAYER_PROFILES)
    assert len(episodes) == report.episodes
    assert {(row.player_profile, row.seed) for row in episodes} == {(profile, seed) for profile in PLAYER_PROFILES for seed in (100, 101)}
    assert all(metrics.episodes == 2 for metrics in report.metrics_by_profile.values())
    assert sum(sum(results.values()) for results in report.results_by_profile.values()) == report.episodes
    assert asdict(report)["policy_name"] == "Rule"


def test_episode_metrics_are_reproducible_and_json_finite():
    first = run_episode(RuleBossPolicy(), seed=200000, player_profile="aggressive")
    second = run_episode(RuleBossPolicy(), seed=200000, player_profile="aggressive")
    assert first == second
    json.dumps(asdict(first), allow_nan=False)
    assert sum(first.action_counts.values()) + first.state_locked_decisions == first.decisions


@pytest.mark.parametrize("first,count", [(49999, 2), (50000, 1), (50299, 1), (0, 50300)])
def test_holdout_seed_ranges_reject_selection_overlap(first, count):
    with pytest.raises(ValueError, match="selection"):
        validate_holdout_seeds(first, count)


@pytest.mark.parametrize("first,count", [(49999, 1), (50300, 1), (200000, 300)])
def test_holdout_seed_ranges_allow_separate_protocol(first, count):
    validate_holdout_seeds(first, count)


@pytest.mark.parametrize("first,count", [(-1, 2), (1, 0), (1, -1)])
def test_holdout_requires_nonnegative_seeds_and_positive_count(first, count):
    with pytest.raises(ValueError):
        validate_holdout_seeds(first, count)


def test_frozen_adapter_uses_runtime_and_explicit_locked_placeholder():
    sim = BossPolicySim(seed=2, profile="aggressive")
    calls = []

    def decide(values):
        calls.append(values)
        return SimpleNamespace(actionable=False, action=None, reason="state_locked")

    policy = FrozenBossPolicy(SimpleNamespace(decide=decide))
    assert policy.select_action(sim.state.observation(), sim.state) == BossAction.PURSUE
    assert calls == [list(sim.state.observation())]


def test_locked_placeholder_is_excluded_from_action_distribution():
    class Runtime:
        def decide(self, observation):
            if not any(observation[-len(BossAction):]):
                return SimpleNamespace(actionable=False, action=None, reason="state_locked")
            legal = [index for index, value in enumerate(observation[-len(BossAction):]) if value >= 0.5]
            return SimpleNamespace(actionable=True, action=BossAction(legal[0]), reason="policy_selected")

    episode = run_episode(FrozenBossPolicy(Runtime()), seed=7, player_profile="aggressive")
    assert episode.state_locked_decisions > 0
    # Sim transitions can reject a previously available action; those remain
    # visible instead of being mistaken for a runtime/mask acceptance promise.
    assert sum(episode.action_counts.values()) == episode.accepted_actions + episode.rejected_actions
    assert episode.accepted_actions + episode.rejected_actions + episode.state_locked_decisions == episode.decisions


@pytest.mark.parametrize("decision", [
    SimpleNamespace(actionable=True, action=None, reason="policy_selected"),
    SimpleNamespace(actionable=False, action=None, reason="unexpected"),
    SimpleNamespace(actionable=False, action=BossAction.PURSUE, reason="state_locked"),
])
def test_frozen_adapter_rejects_inconsistent_runtime_decisions(decision):
    policy = FrozenBossPolicy(SimpleNamespace(decide=lambda _: decision))
    with pytest.raises(ValueError):
        policy.select_action((0.0,) * 26, None)


@pytest.mark.parametrize("arguments", [
    ["--episodes", "0"], ["--seed", "-1"],
    ["--policy", "frozen"], ["--model", "unused.zip"],
    ["--policy", "compare", "--model", "model.zip", "--out", "unused", "--seed", "50000"],
])
def test_cli_rejects_invalid_protocol(arguments):
    with pytest.raises(SystemExit):
        evaluator.parse_args(arguments)


def test_rule_evidence_bundle_has_raw_records_counts_hashes_and_source(tmp_path):
    output = tmp_path / "rule-evidence"
    args = evaluator.parse_args(["--policy", "rule", "--episodes", "1", "--out", str(output)])
    summary = evaluator.run_experiment(args)
    assert summary["episodes_per_policy"] == len(PLAYER_PROFILES)
    assert summary["total_episode_records"] == len(PLAYER_PROFILES)
    rows = [json.loads(line) for line in (output / "episodes.jsonl").read_text().splitlines()]
    assert {row["player_profile"] for row in rows} == set(PLAYER_PROFILES)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["seed_protocol"]["last_inclusive"] == 0
    assert manifest["source"]["source_sha256"]["scripts/rl/boss/eval.py"]
    assert manifest["software"]["python"]
    assert manifest["model"] is None
    for name, artifact in manifest["artifacts"].items():
        assert sha256((output / name).read_bytes()).hexdigest() == artifact["sha256"]
    with pytest.raises(SystemExit):
        evaluator.parse_args(["--out", str(output)])
    with pytest.raises(FileExistsError):
        evaluator.run_experiment(args)


def test_compare_pairs_each_profile_and_seed_and_keeps_existing_candidate(tmp_path, monkeypatch):
    class FakeFrozen(RuleBossPolicy):
        runtime = SimpleNamespace(model_path=tmp_path / "reviewed.zip", provenance={"model_sha256": "d" * 64})

    monkeypatch.setattr(evaluator.FrozenBossPolicy, "from_model", lambda _: FakeFrozen())
    monkeypatch.setattr(evaluator, "_archive_frozen_materials", lambda *_: {})
    output = tmp_path / "paired-evidence"
    args = evaluator.parse_args(["--policy", "compare", "--model", "reviewed.zip", "--out", str(output), "--episodes", "2"])
    assert args.seed == DEFAULT_HOLDOUT_SEED
    summary = evaluator.run_experiment(args)
    assert summary["total_episode_records"] == 12
    assert all(report["episodes"] == 6 for report in summary["reports"].values())
    assert all(metrics["pairs"] == 2 for metrics in summary["paired_comparison_by_profile"].values())
    assert all(metrics["mean_reward_delta_frozen_minus_rule"] == 0 for metrics in summary["paired_comparison_by_profile"].values())
    rows = [json.loads(line) for line in (output / "episodes.jsonl").read_text().splitlines()]
    keys = {name: {(row["player_profile"], row["seed"]) for row in rows if row["policy"] == name} for name in ("rule", "frozen")}
    assert keys["rule"] == keys["frozen"]
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["seed_protocol"]["candidate_retrained_or_reselected"] is False
    assert manifest["model"]["verified_provenance"]["model_sha256"] == "d" * 64


def test_frozen_material_archival_requires_the_previously_verified_hash(tmp_path, monkeypatch):
    from rl.boss import release

    data = b'{"prior_material": true}\n'
    for name in ("selection", "training"):
        (tmp_path / f"{name}.json").write_bytes(data)
    descriptor = {f"{name}_file": f"{name}.json" for name in ("selection", "training")}
    monkeypatch.setattr(release, "load_release_descriptor", lambda: descriptor)
    runtime = SimpleNamespace(model_path=tmp_path / "model.zip", provenance={f"{name}_sha256": sha256(data).hexdigest() for name in ("selection", "training")})
    output = tmp_path / "output"
    output.mkdir()
    artifacts = evaluator._archive_frozen_materials(FrozenBossPolicy(runtime), output)
    assert set(artifacts) == {"frozen-selection.json", "frozen-training.json"}
    assert (output / "frozen-selection.json").read_bytes() == data
    (tmp_path / "selection.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed after validation"):
        evaluator._archive_frozen_materials(FrozenBossPolicy(runtime), output)


def test_nonfinite_episode_is_rejected_instead_of_emitting_invalid_json(tmp_path, monkeypatch):
    episode = run_episode(RuleBossPolicy(), seed=1, player_profile="aggressive")
    monkeypatch.setattr("rl.boss.evaluation.run_episode", lambda *args, **kwargs: replace(episode, total_reward=float("nan")))
    args = evaluator.parse_args(["--episodes", "1", "--out", str(tmp_path / "nonfinite")])
    with pytest.raises(ValueError, match="JSON compliant"):
        evaluator.run_experiment(args)
    assert not (args.out / "manifest.json").exists()
