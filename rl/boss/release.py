"""Verify the reviewed frozen release before deserializing its model archive.

The descriptor is part of the trusted application release. Sidecars beside a
model cannot nominate their own replacement hash. Model archives can contain
Python serialized objects, so only the pinned release is ever loaded.
"""

from hashlib import sha256
import json
from pathlib import Path
import sys

from rl.boss.contract import ACTION_COUNT, BossAction, FEATURE_NAMES, SCHEMA_VERSION
from rl.boss.rewards import REWARD_REVISION
from rl.boss.sim import SIMULATION_REVISION


def release_descriptor_path() -> Path:
    return Path(__file__).with_name("deployment.json")


def load_release_descriptor() -> dict[str, object]:
    descriptor = _read_object(release_descriptor_path())
    expected = {
        "schema_version": SCHEMA_VERSION,
        "simulation_revision": SIMULATION_REVISION,
        "reward_revision": REWARD_REVISION,
    }
    if any(descriptor.get(key) != value for key, value in expected.items()):
        raise ValueError("frozen release descriptor does not match the runtime contract")
    for key in ("model_sha256", "selection_sha256", "training_sha256"):
        digest = descriptor.get(key)
        if (not isinstance(digest, str) or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)):
            raise ValueError(f"invalid frozen release digest: {key}")
    for key in ("model_file", "selection_file", "training_file"):
        name = descriptor.get(key)
        if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError(f"invalid frozen release filename: {key}")
    if not descriptor.get("release_id") or not descriptor.get("model_id"):
        raise ValueError("frozen release identity is missing")
    return descriptor


def default_model_path() -> Path:
    model_file = str(load_release_descriptor()["model_file"])
    relative = Path("models") / "rl" / "boss" / "deployment" / model_file
    if getattr(sys, "frozen", False):
        roots = [Path(sys.executable).resolve().parent]
        if getattr(sys, "_MEIPASS", None):
            roots.append(Path(sys._MEIPASS))
        return next((root / relative for root in roots if (root / relative).is_file()),
                    roots[0] / relative)
    return Path(__file__).resolve().parents[2] / relative


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read frozen release material: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"frozen release material is not an object: {path.name}")
    return value


def _verify_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"frozen release material is missing: {path.name}")
    actual = sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"frozen release SHA256 mismatch: {path.name}")


def validate_frozen_artifact(model_path: Path) -> dict[str, object]:
    """Return provenance only after checking pinned bytes and semantic contracts."""
    descriptor = load_release_descriptor()
    if model_path.name != descriptor["model_file"]:
        raise ValueError("model filename is not the reviewed frozen release")
    _verify_hash(model_path, str(descriptor["model_sha256"]))
    selection_path = model_path.with_name(str(descriptor["selection_file"]))
    training_path = model_path.with_name(str(descriptor["training_file"]))
    _verify_hash(selection_path, str(descriptor["selection_sha256"]))
    _verify_hash(training_path, str(descriptor["training_sha256"]))
    selection = _read_object(selection_path)
    training = _read_object(training_path)
    for material in (selection, training):
        for key in ("schema_version", "simulation_revision", "reward_revision"):
            if material.get(key) != descriptor[key]:
                raise ValueError(f"frozen release {key} mismatch")
    if selection.get("artifact_type") != "frozen_boss_policy":
        raise ValueError("selection material is not a frozen policy")
    if selection.get("sha256") != descriptor["model_sha256"]:
        raise ValueError("selection model digest differs from the trusted release")
    if (selection.get("source_seed") != descriptor["source_seed"]
            or training.get("seed") != descriptor["source_seed"]):
        raise ValueError("frozen release source seed mismatch")
    source_model = str(selection.get("source_model", "")).replace("\\", "/")
    training_model = str(training.get("model", "")).replace("\\", "/")
    if not source_model or source_model != training_model:
        raise ValueError("training and selection source models differ")
    if training.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("frozen release ordered observation features mismatch")
    if training.get("actions") != {action.name: int(action) for action in BossAction}:
        raise ValueError("frozen release action mapping mismatch")
    return {
        "source_seed": descriptor["source_seed"],
        "source_model": source_model,
        "training_total_timesteps": training.get("total_timesteps"),
        "training_episode_seed_strategy": training.get("episode_seed_strategy"),
        "release_id": descriptor["release_id"],
        "model_id": descriptor["model_id"],
        "model_sha256": descriptor["model_sha256"],
        "selection_sha256": descriptor["selection_sha256"],
        "training_sha256": descriptor["training_sha256"],
        "schema_version": SCHEMA_VERSION,
        "simulation_revision": SIMULATION_REVISION,
        "reward_revision": REWARD_REVISION,
        "observation_dimension": len(FEATURE_NAMES),
        "action_count": ACTION_COUNT,
    }
