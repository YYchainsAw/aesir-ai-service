"""Pinned release verification remains independent of ML dependencies."""

from hashlib import sha256
import json

import pytest

from rl.boss import release
from rl.boss.contract import BossAction, FEATURE_NAMES


def _artifact(tmp_path, monkeypatch):
    descriptor = release.load_release_descriptor()
    model = tmp_path / str(descriptor["model_file"])
    model.write_bytes(b"pinned synthetic archive; never deserialized")
    selection = {
        "artifact_type": "frozen_boss_policy", "schema_version": 4,
        "simulation_revision": "boss-sim-005", "reward_revision": "boss-reward-003",
        "source_seed": 1, "source_model": "models/source.zip",
        "sha256": sha256(model.read_bytes()).hexdigest(),
    }
    training = {
        "schema_version": 4, "simulation_revision": "boss-sim-005",
        "reward_revision": "boss-reward-003", "seed": 1,
        "model": "models/source.zip", "feature_names": list(FEATURE_NAMES),
        "actions": {action.name: int(action) for action in BossAction},
    }
    for kind, material in (("selection", selection), ("training", training)):
        path = model.with_name(str(descriptor[f"{kind}_file"]))
        path.write_text(json.dumps(material), encoding="utf-8")
        descriptor[f"{kind}_sha256"] = sha256(path.read_bytes()).hexdigest()
    descriptor["model_sha256"] = selection["sha256"]
    monkeypatch.setattr(release, "load_release_descriptor", lambda: descriptor)
    return model, descriptor


def test_frozen_artifact_validates_pinned_materials(tmp_path, monkeypatch):
    model, descriptor = _artifact(tmp_path, monkeypatch)
    result = release.validate_frozen_artifact(model)
    assert result["model_sha256"] == descriptor["model_sha256"]
    assert result["source_model"] == "models/source.zip"


@pytest.mark.parametrize("kind", ["model", "selection", "training"])
def test_release_rejects_tampered_bytes_before_loading(tmp_path, monkeypatch, kind):
    model, descriptor = _artifact(tmp_path, monkeypatch)
    path = model if kind == "model" else model.with_name(str(descriptor[f"{kind}_file"]))
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        release.validate_frozen_artifact(model)


def test_release_sidecar_cannot_nominate_another_model_hash(tmp_path, monkeypatch):
    model, descriptor = _artifact(tmp_path, monkeypatch)
    model.write_bytes(b"substituted archive")
    path = model.with_name(str(descriptor["selection_file"]))
    material = json.loads(path.read_text())
    material["sha256"] = sha256(model.read_bytes()).hexdigest()
    path.write_text(json.dumps(material))
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        release.validate_frozen_artifact(model)


@pytest.mark.parametrize("field,value", [
    ("feature_names", list(reversed(FEATURE_NAMES))),
    ("actions", {action.name: int(action) + 1 for action in BossAction}),
    ("schema_version", 3), ("simulation_revision", "boss-sim-other"),
    ("reward_revision", "boss-reward-other"), ("seed", 2),
    ("model", "another-source.zip"),
])
def test_semantic_contract_is_checked_even_with_matching_material_hash(
        tmp_path, monkeypatch, field, value):
    model, descriptor = _artifact(tmp_path, monkeypatch)
    path = model.with_name(str(descriptor["training_file"]))
    material = json.loads(path.read_text())
    material[field] = value
    path.write_text(json.dumps(material))
    descriptor["training_sha256"] = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        release.validate_frozen_artifact(model)


def test_missing_release_material_is_rejected(tmp_path, monkeypatch):
    model, descriptor = _artifact(tmp_path, monkeypatch)
    model.with_name(str(descriptor["training_file"])).unlink()
    with pytest.raises(FileNotFoundError):
        release.validate_frozen_artifact(model)

def test_frozen_default_path_uses_executable_bundle(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "boss-policy.exe"))
    assert release.default_model_path() == (
        tmp_path / "models/rl/boss/deployment/boss_policy_schema_v4_sim005.zip")


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "118.89.95.228", "localhost", "example.com"])
def test_source_server_rejects_nonliteral_or_public_bind(monkeypatch, host):
    import sys
    from scripts.rl.boss.serve import parse_args
    monkeypatch.setattr(sys, "argv", ["serve", "--host", host])
    with pytest.raises(SystemExit) as error:
        parse_args()
    assert error.value.code == 2


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_source_server_accepts_only_loopback_bind(monkeypatch, host):
    import sys
    from scripts.rl.boss.serve import parse_args
    monkeypatch.setattr(sys, "argv", ["serve", "--host", host])
    assert parse_args().host == host


@pytest.mark.parametrize("port", ["0", "65536"])
def test_source_server_rejects_invalid_port(monkeypatch, port):
    import sys
    from scripts.rl.boss.serve import parse_args
    monkeypatch.setattr(sys, "argv", ["serve", "--port", port])
    with pytest.raises(SystemExit) as error:
        parse_args()
    assert error.value.code == 2
