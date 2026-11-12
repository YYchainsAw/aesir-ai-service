"""Inventory Boss delivery files and installed metadata without loading a policy.

No inference, training, dependency imports, package installation or network calls.
Example: python -m scripts.rl.boss.inventory
"""
from __future__ import annotations

from hashlib import sha256
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import subprocess
from zipfile import BadZipFile, ZipFile
import argparse

from rl.boss.contract import ACTION_COUNT, FEATURE_NAMES, SCHEMA_VERSION, BossAction
from rl.boss.artifact import EXPECTED_SHA256, MODEL_NAME

ROOT = Path(__file__).resolve().parents[3]


def digest(path: Path) -> str:
    result = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def zip_metadata(path: Path) -> dict:
    """Read only SB3's bounded JSON metadata, never pickle/cloudpickle/tensors."""
    try:
        with ZipFile(path) as archive:
            info = archive.getinfo("data")
            if info.file_size > 1024 * 1024:
                return {"metadata_state": "over_size_limit"}
            data = json.loads(archive.read(info))
        if not isinstance(data, dict):
            return {"metadata_state": "invalid_json_object"}
        obs = data.get("observation_space")
        action = data.get("action_space")
        shape = obs.get("_shape") if isinstance(obs, dict) else None
        count = action.get("n") if isinstance(action, dict) else None
        if not isinstance(shape, list) or not all(type(x) is int for x in shape):
            shape = None
        if isinstance(count, str) and count.isdecimal():
            count = int(count)
        if type(count) is not int:
            count = None
        return {"metadata_state": "json_read_only", "declared_observation_shape": shape,
                "declared_action_count": count,
                "declared_dimensions_match": shape == [len(FEATURE_NAMES)] and count == ACTION_COUNT}
    except (OSError, BadZipFile, KeyError, ValueError, RuntimeError, NotImplementedError, EOFError, RecursionError):
        return {"metadata_state": "unreadable_or_no_json_data"}


def dependency_inventory() -> list[dict]:
    result = []
    for line in (ROOT / "requirements-boss-inference.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, expected = line.strip().split("==", 1)
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        result.append({"distribution": name, "pinned_version": expected,
                       "installed_version": installed,
                       "pin_matches": installed is not None and installed.split("+", 1)[0] == expected})
    return result


def inventory(model_root: Path) -> dict:
    deployment = model_root / "boss/deployment"
    candidate = deployment / f"{MODEL_NAME}.zip"
    artifacts = []
    for path in (candidate, deployment / f"{MODEL_NAME}.selection.json",
                 deployment / f"{MODEL_NAME}.training.manifest.json"):
        item = {"path": str(path), "present": path.is_file()}
        if item["present"]:
            item.update(bytes=path.stat().st_size, sha256=digest(path))
            if path == candidate:
                item["matches_frozen_candidate"] = item["sha256"] == EXPECTED_SHA256
        artifacts.append(item)
    local_models = []
    if model_root.is_dir():
        for path in sorted(model_root.rglob("*.zip")):
            try:
                checksum = digest(path)
                local_models.append({"path": str(path), "bytes": path.stat().st_size,
                                     "sha256": checksum, "matches_frozen_candidate": checksum == EXPECTED_SHA256,
                                     **zip_metadata(path)})
            except OSError:
                local_models.append({"path": str(path), "readable": False})
    dependencies = dependency_inventory()
    blockers = ["missing:" + item["path"] for item in artifacts if not item["present"]]
    if artifacts[0]["present"] and not artifacts[0]["matches_frozen_candidate"]:
        blockers.append("frozen_candidate_sha256_mismatch")
    blockers.extend("dependency:" + item["distribution"] for item in dependencies if not item["pin_matches"])
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                         text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {
        "scope": "offline_file_and_distribution_inventory",
        "service_commit": commit,
        "inventory_script_sha256": digest(Path(__file__)),
        "inference_requirements_sha256": digest(ROOT / "requirements-boss-inference.txt"),
        "platform": platform.system(), "python_version": platform.python_version(),
        "expected_contract": {"protocol_version": "1.0", "schema_version": SCHEMA_VERSION,
                              "feature_names": list(FEATURE_NAMES), "action_count": ACTION_COUNT,
                              "actions": [{"id": int(action), "python_name": action.name,
                                           "ue_name": "".join(part.title() for part in action.name.split("_"))}
                                          for action in BossAction],
                              "frozen_candidate_sha256": EXPECTED_SHA256},
        "required_artifacts": artifacts, "local_model_metadata": local_models,
        "inference_dependencies": dependencies, "blockers": blockers,
        "materials_state": "blocked" if blockers else "present_but_not_runtime_verified",
        "policy_loaded": False, "inference_performed": False,
        "runtime_acceptance": "deferred",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, default=ROOT / "models/rl")
    parser.add_argument("--output", type=Path, default=ROOT / "data/runtime/boss-delivery/inventory.json")
    args = parser.parse_args()
    report = inventory(args.model_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.output), "materials_state": report["materials_state"],
                      "blockers": report["blockers"], "runtime_acceptance": "deferred"}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
