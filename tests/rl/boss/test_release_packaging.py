"""Packaging checks remain dependency-free on the NPC server."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from scripts.rl.boss import build_release, release_entry


def make_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "release with spaces"
    (root / "_internal").mkdir(parents=True)
    (root / "aesir-boss-policy.exe").write_bytes(b"synthetic executable")
    (root / "_internal/material.bin").write_bytes(b"not a model")
    build_release.write_manifest(root, provenance={"release_id": "test"}, versions={"torch": "test"},
                                 source_commit="a" * 40, source_files={}, licenses=[])
    return root


def test_inventory_verifies_all_bytes_and_retains_source_identity(tmp_path):
    root = make_bundle(tmp_path)
    manifest = release_entry.verify_bundle(root)
    assert manifest["source_commit"] == "a" * 40
    assert "caller-declared" in manifest["source_commit_origin"]
    assert set(manifest["files"]) == {"aesir-boss-policy.exe", "_internal/material.bin"}


def test_inventory_detects_changed_dependency_without_loading_model(tmp_path):
    root = make_bundle(tmp_path)
    (root / "_internal/material.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        release_entry.verify_bundle(root)


@pytest.mark.parametrize("change", ["extra", "missing"])
def test_inventory_rejects_unlisted_and_missing_files(tmp_path, change):
    root = make_bundle(tmp_path)
    if change == "extra":
        (root / ".env").write_text("unwanted")
    else:
        (root / "_internal/material.bin").unlink()
    with pytest.raises(ValueError):
        release_entry.verify_bundle(root)


@pytest.mark.parametrize("name", ["../outside", "/outside", "C:/outside", "dir\\outside",
                                  "release-manifest.json"])
def test_inventory_rejects_paths_outside_release(tmp_path, name):
    root = make_bundle(tmp_path)
    path = root / "release-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"] = {name: "0" * 64}
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe path"):
        release_entry.verify_bundle(root)


@pytest.mark.parametrize("inventory", [None, {}, {"file": "bad"}, {"file": 12}])
def test_inventory_rejects_invalid_shape(tmp_path, inventory):
    root = make_bundle(tmp_path)
    path = root / "release-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"] = inventory
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        release_entry.verify_bundle(root)


def test_inventory_rejects_linked_material(tmp_path):
    root = make_bundle(tmp_path)
    target = root / "_internal/material.bin"
    outside = tmp_path / "outside"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="missing or linked"):
        release_entry.verify_bundle(root)


@pytest.mark.parametrize("argv", [["--host", "0.0.0.0"], ["--host", "::"],
                                  ["--port", "0"], ["--port", "65536"],
                                  ["--verify", "--self-test"]])
def test_launcher_rejects_external_binding_and_invalid_options(argv):
    with pytest.raises(SystemExit) as error:
        release_entry.parse_args(argv)
    assert error.value.code == 2


def test_verify_mode_does_not_import_inference_or_deserialize(tmp_path, monkeypatch, capsys):
    root = make_bundle(tmp_path)
    from rl.boss import release

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(root / "aesir-boss-policy.exe"))
    monkeypatch.setenv("AESIR_BOSS_POLICY_MODEL", "")
    monkeypatch.setattr(release, "default_model_path", lambda: root / "unused.zip")
    monkeypatch.setattr(release, "validate_frozen_artifact", lambda _: {"release_id": "test"})
    monkeypatch.setitem(sys.modules, "rl.boss.inference", None)
    assert release_entry.main(["--verify"]) == 0
    assert json.loads(capsys.readouterr().out)["model_loaded"] is False


def test_launcher_rejects_model_override_before_any_model_read(monkeypatch, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("AESIR_BOSS_POLICY_MODEL", "untrusted.zip")
    assert release_entry.main(["--verify"]) == 2
    assert "does not accept" in capsys.readouterr().err


def test_builder_never_overwrites_existing_output(tmp_path, monkeypatch):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep").write_text("preserved")
    monkeypatch.setattr(build_release, "validate_runtime", lambda: pytest.fail("runtime inspection after overwrite"))
    result = build_release.main(["--model-dir", str(tmp_path / "missing"), "--output", str(output),
                                 "--source-commit", "a" * 40])
    assert result == 2
    assert (output / "keep").read_text() == "preserved"


def test_build_command_uses_argument_boundaries_and_includes_descriptor(tmp_path):
    root = tmp_path / "source with spaces"
    model = tmp_path / "model with spaces"
    work = tmp_path / "build with spaces"
    site = tmp_path / "ML environment"
    command = build_release.pyinstaller_command(root, model, work, [site])
    assert isinstance(command, list)
    assert str(root) in command and str(site) in command
    assert command[command.index("--name") + 1] == "aesir-boss-policy"
    assert any("rl/boss/deployment.json" in item.replace("\\", "/") for item in command)
    assert any("models/rl/boss/deployment" in item for item in command)
    assert "--onedir" in command and "--onefile" not in command
    assert command[-1] == str(root / "scripts/rl/boss/release_entry.py")


def test_source_commit_requires_full_hash():
    with pytest.raises(SystemExit):
        build_release.parse_args(["--model-dir", "models", "--output", "new", "--source-commit", "main"])


@pytest.fixture
def simulated_windows_runtime(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(build_release.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(build_release.platform, "python_version", lambda: "3.11.9")
    pins = {**build_release.RUNTIME_PINS, "pyinstaller": build_release.PYINSTALLER_VERSION}
    monkeypatch.setattr(build_release.metadata, "version", pins.__getitem__)
    torch = SimpleNamespace(__version__="2.7.1+cpu", version=SimpleNamespace(cuda=None))
    monkeypatch.setitem(sys.modules, "torch", torch)
    return pins, torch


def test_runtime_accepts_cpu_build_when_wheel_metadata_has_no_local_suffix(simulated_windows_runtime):
    versions = build_release.validate_runtime()
    assert versions["torch"] == "2.7.1"
    assert versions["torch_runtime"] == "2.7.1+cpu"
    assert versions["torch_cuda"] == "none"


@pytest.mark.parametrize("version,cuda", [("2.7.1+cu126", "12.6"), ("2.7.1+cpu", "12.6"),
                                         ("2.7.1", None), ("2.8.0+cpu", None)])
def test_runtime_rejects_cuda_and_unreviewed_torch_binaries(simulated_windows_runtime, version, cuda):
    _, torch = simulated_windows_runtime
    torch.__version__ = version
    torch.version.cuda = cuda
    with pytest.raises(ValueError, match="CPU wheel"):
        build_release.validate_runtime()


@pytest.mark.parametrize("distribution", list(build_release.RUNTIME_PINS))
def test_runtime_rejects_dependency_metadata_drift(simulated_windows_runtime, distribution):
    pins, _ = simulated_windows_runtime
    pins[distribution] = "wrong-version"
    with pytest.raises(ValueError, match="dependency mismatch"):
        build_release.validate_runtime()


def test_runtime_rejects_unreviewed_builder(simulated_windows_runtime):
    pins, _ = simulated_windows_runtime
    pins["pyinstaller"] = "wrong-version"
    with pytest.raises(ValueError, match="build tool"):
        build_release.validate_runtime()


def test_runtime_rejects_npc_server_python_as_boss_runtime(simulated_windows_runtime, monkeypatch):
    monkeypatch.setattr(build_release.platform, "python_version", lambda: "3.12.15")
    with pytest.raises(ValueError, match="NPC server requirements are separate"):
        build_release.validate_runtime()
