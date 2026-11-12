"""Frozen evaluation evidence and preflight checks without SB3 or training."""
import json
from types import SimpleNamespace

import pytest

from rl.boss.evaluation import evaluate_policy
from rl.boss.policy import RuleBossPolicy
from scripts.rl.boss import eval_frozen
from scripts.rl.boss.inventory import zip_metadata


@pytest.mark.parametrize("episodes,seed", [(0, 200000), (1, -1), (1, 50000),
                                         (1, 50299), (2, 49999), (60000, 0)])
def test_invalid_or_selection_overlapping_seeds_rejected(episodes, seed):
    with pytest.raises(ValueError):
        eval_frozen.validate_seeds(episodes, seed)


@pytest.mark.parametrize("episodes,seed", [(1, 49999), (1, 50300), (100, 200000)])
def test_disjoint_seed_intervals_accepted(episodes, seed):
    eval_frozen.validate_seeds(episodes, seed)


def test_untrusted_zip_rejected_before_sb3_import(tmp_path, monkeypatch):
    import builtins

    original_import = builtins.__import__

    def guard(name, *args, **kwargs):
        assert not name.startswith("sb3_contrib"), "untrusted ZIP reached deserialization"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    model = tmp_path / "wrong.zip"
    model.write_bytes(b"not the frozen model")
    with pytest.raises(RuntimeError, match="MODEL_SHA256_MISMATCH"):
        eval_frozen.load_frozen_policy(model)


@pytest.mark.parametrize("shape,count", [((17,), 9), ((26,), 7), ((26, 1), 9)])
def test_incompatible_model_spaces_rejected(shape, count):
    model = SimpleNamespace(observation_space=SimpleNamespace(shape=shape),
                            action_space=SimpleNamespace(n=count))
    with pytest.raises(ValueError, match="space"):
        eval_frozen.FrozenBossPolicy(model)


@pytest.mark.parametrize("selected,legal", [(8, True), (0, False), (9, False)])
def test_frozen_adapter_uses_deterministic_masked_cpu_input(selected, legal):
    np = pytest.importorskip("numpy")

    class Model:
        observation_space = SimpleNamespace(shape=(26,))
        action_space = SimpleNamespace(n=9)

        def predict(self, observation, deterministic, action_masks):
            assert observation.shape == (26,)
            assert observation.dtype == np.float32
            assert deterministic is True
            assert action_masks.dtype == np.bool_
            assert list(np.flatnonzero(action_masks)) == [8]
            return selected, None

    observation = [0.0] * 26
    observation[-1] = 1.0
    policy = eval_frozen.FrozenBossPolicy(Model())
    if legal:
        assert policy.select_action(observation, None) == 8
    else:
        with pytest.raises(ValueError):
            policy.select_action(observation, None)


def test_missing_model_leaves_no_evidence_directory(tmp_path):
    output = tmp_path / "evidence"
    with pytest.raises(RuntimeError, match="MODEL_NOT_FOUND"):
        eval_frozen.run_evaluation(model_path=tmp_path / "absent.zip", output=output,
                                   episodes=1, seed=200000)
    assert not output.exists()


def test_existing_evidence_is_preserved(tmp_path):
    marker = tmp_path / "summary.json"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        eval_frozen.run_evaluation(model_path=tmp_path / "absent.zip", output=tmp_path,
                                   episodes=1, seed=200000)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_episode_sink_and_summary_describe_same_run():
    episodes = []
    report = evaluate_policy(RuleBossPolicy(), policy_name="rule", episodes_per_profile=2,
                             base_seed=200000, on_episode=episodes.append)
    assert len(episodes) == report.episodes == 6
    assert report.mean_reward == pytest.approx(sum(e.total_reward for e in episodes) / 6)
    assert report.boss_win_rate == sum(e.result == "boss_victory" for e in episodes) / 6
    assert [(e.player_profile, e.seed) for e in episodes] == [
        (profile, seed) for profile in ("aggressive", "defensive", "evasive")
        for seed in (200000, 200001)
    ]


def test_comparison_evidence_pairing_hashes_and_reproduction(tmp_path, monkeypatch):
    # Exercises evidence generation only; never describes this stand-in as PPO performance.
    policy = RuleBossPolicy()
    policy.validation = {"actual": {"sha256": eval_frozen.EXPECTED_SHA256}}
    monkeypatch.setattr(eval_frozen, "load_frozen_policy", lambda path: policy)
    output = tmp_path / "run"
    summary = eval_frozen.run_evaluation(model_path=tmp_path / "fixture.zip", output=output,
                                        episodes=2, seed=200000)
    stored = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary == stored
    rows = [json.loads(line) for line in (output / "episodes.jsonl").read_text().splitlines()]
    assert len(rows) == 12
    assert summary["episodes_sha256"] == eval_frozen.digest(output / "episodes.jsonl")
    assert summary["source_sha256"]
    assert summary["seed_plan"]["training_seed_independence"] == "not_established"
    assert summary["ue_acceptance"] == "not_performed"
    assert "-replay" in summary["reproduce_argv"][-1]
    first, second = rows[:6], rows[6:]
    for rule, frozen in zip(first, second):
        assert rule.pop("policy") == "rule_baseline"
        assert frozen.pop("policy") == "frozen_ppo"
        assert rule == frozen


def test_failed_run_does_not_publish_completed_summary(tmp_path, monkeypatch):
    class BrokenPolicy:
        def select_action(self, observation, state):
            raise ValueError("prediction failed")

    monkeypatch.setattr(eval_frozen, "load_frozen_policy", lambda path: BrokenPolicy())
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="prediction failed"):
        eval_frozen.run_evaluation(model_path=tmp_path / "fixture.zip", output=output,
                                   episodes=1, seed=200000)
    assert not (output / "summary.json").exists()
    assert len((output / "episodes.jsonl").read_text().splitlines()) == 3


def test_inventory_reads_only_json_metadata(tmp_path):
    from zipfile import ZipFile

    path = tmp_path / "model.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("data", json.dumps({"observation_space": {"_shape": [17]},
                                            "action_space": {"n": "7"}}))
        archive.writestr("policy.pth", b"never deserialize this")
    report = zip_metadata(path)
    assert report["declared_dimensions_match"] is False
    assert report["declared_observation_shape"] == [17]
    assert report["declared_action_count"] == 7


def test_inventory_bounds_json_size(tmp_path):
    from zipfile import ZipFile

    path = tmp_path / "large.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("data", b" " * (1024 * 1024 + 1))
    assert zip_metadata(path) == {"metadata_state": "over_size_limit"}


def test_bad_zip_does_not_abort_other_model_inventory(tmp_path):
    from zipfile import ZipFile
    from scripts.rl.boss.inventory import inventory
    bad = tmp_path / "bad.zip"
    with ZipFile(bad, "w") as archive:
        archive.writestr("data", "{}")
    data = bytearray(bad.read_bytes())
    for signature, offset in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        position = data.index(signature) + offset
        data[position:position+2] = (99).to_bytes(2, "little")
    bad.write_bytes(data)
    with ZipFile(tmp_path / "good.zip", "w") as archive:
        archive.writestr("data", json.dumps({"observation_space": {"_shape": [26]},
                                            "action_space": {"n": 9}}))
    models = inventory(tmp_path)["local_model_metadata"]
    assert len(models) == 2
    assert models[0]["metadata_state"] == "unreadable_or_no_json_data"
    assert models[1]["declared_dimensions_match"] is True
