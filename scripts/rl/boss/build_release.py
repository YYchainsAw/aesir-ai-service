"""Build the reviewed Boss CPU policy as a native Windows onedir release.

Run with the isolated Python 3.11.9 build environment, not the NPC server's
Python environment. Existing ML site-packages may be reused read-only through
--runtime-site-packages. No dependency or model is downloaded by this tool.
"""

import argparse
from datetime import datetime, timezone
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import uuid

from scripts.rl.boss.release_entry import file_sha256

APP_NAME = "aesir-boss-policy"
PYINSTALLER_VERSION = "6.22.3"
PYTHON_VERSION = "3.11.9"
RUNTIME_PINS = {
    "torch": "2.7.1",
    "numpy": "2.4.6",
    "stable-baselines3": "2.7.1",
    "sb3-contrib": "2.7.1",
    "gymnasium": "1.2.3",
    "fastapi": "0.141.1",
    "uvicorn": "0.52.4",
}
COLLECT_PACKAGES = ("torch", "numpy", "stable_baselines3", "sb3_contrib", "gymnasium")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new output directory; never overwritten")
    parser.add_argument("--runtime-site-packages", type=Path, action="append", default=[])
    parser.add_argument("--source-commit", required=True, help="reviewed 40-character source commit")
    parser.add_argument("--plan", action="store_true", help="validate inputs and print build plan only")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        parser.error("source-commit must be a full lowercase Git SHA1")
    return args


def validate_runtime() -> dict[str, str]:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("build this release natively on 64-bit Windows")
    if platform.python_version() != PYTHON_VERSION:
        raise ValueError(f"Boss release requires Python {PYTHON_VERSION}; NPC server requirements are separate")
    versions = {name: metadata.version(name) for name in RUNTIME_PINS}
    for name, expected in RUNTIME_PINS.items():
        if versions[name] != expected:
            raise ValueError(f"release dependency mismatch: {name} requires {expected}, found {versions[name]}")
    if metadata.version("pyinstaller") != PYINSTALLER_VERSION:
        raise ValueError(f"build tool requires PyInstaller {PYINSTALLER_VERSION}")
    import torch

    if torch.__version__ != "2.7.1+cpu" or torch.version.cuda is not None:
        raise ValueError("release requires the verified torch 2.7.1+cpu CPU wheel (no CUDA)")
    versions["torch_runtime"] = str(torch.__version__)
    versions["torch_cuda"] = "none"
    return versions


def pyinstaller_command(root: Path, models: Path, work: Path,
                        site_packages: list[Path]) -> list[str]:
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--console", "--noupx", "--name", APP_NAME,
               "--distpath", str(work / "dist"), "--workpath", str(work / "work"),
               "--specpath", str(work), "--paths", str(root),
               "--add-data", f"{models}{os.pathsep}models/rl/boss/deployment",
               "--add-data", f"{root / 'rl/boss/deployment.json'}{os.pathsep}rl/boss",
               "--hidden-import", "uvicorn.logging", "--hidden-import", "uvicorn.loops.asyncio",
               "--hidden-import", "uvicorn.protocols.http.h11_impl",
               "--hidden-import", "uvicorn.lifespan.on",
               "--hidden-import", "cloudpickle.cloudpickle"]
    for directory in site_packages:
        command += ["--paths", str(directory)]
    for package in COLLECT_PACKAGES:
        command += ["--collect-all", package]
    for distribution in (*RUNTIME_PINS, "cloudpickle", "pydantic", "pydantic-core", "starlette"):
        command += ["--copy-metadata", distribution]
    for package in ("app", "sqlalchemy", "pymysql", "tests", "pytest", "IPython", "tkinter", "tensorboard"):
        command += ["--exclude-module", package]
    command += [str(root / "scripts/rl/boss/release_entry.py")]
    return command


def collect_licenses(destination: Path) -> list[dict[str, object]]:
    """Retain installed distributions' license/notice files and package metadata.

    This conservative inventory includes build-environment candidates as well as
    runtime distributions; it does not assert that each candidate is imported.
    """
    result = []
    seen = set()
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name", "unknown")
        version = distribution.version
        identity = (name.lower(), version)
        if identity in seen:
            continue
        seen.add(identity)
        safe_name = re.sub(r"[^a-zA-Z0-9_.+-]", "_", f"{name}-{version}")
        retained = []
        for entry in distribution.files or []:
            basename = Path(str(entry)).name.lower()
            if not (basename.startswith(("license", "licence", "copying", "notice", "authors"))
                    or basename == "metadata"):
                continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file():
                continue
            parts = [part for part in Path(str(entry)).parts if part not in {"..", ".", "/", "\\"}]
            target = destination / safe_name / Path(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            retained.append(target.relative_to(destination).as_posix())
        result.append({"name": name, "version": version, "retained_files": retained})
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise ValueError("Python LICENSE.txt is required for the standalone runtime")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(python_license, destination / "PYTHON-LICENSE.txt")
    return sorted(result, key=lambda item: (str(item["name"]).lower(), str(item["version"])))


def write_manifest(bundle: Path, *, provenance: dict[str, object],
                   versions: dict[str, str], source_commit: str,
                   source_files: dict[str, str], licenses: list[dict[str, object]]) -> dict[str, object]:
    files = {path.relative_to(bundle).as_posix(): file_sha256(path)
             for path in sorted(bundle.rglob("*")) if path.is_file()
             and path != bundle / "release-manifest.json"}
    manifest = {
        "format": "aesir-boss-windows-onedir-v1",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "source_commit_origin": "caller-declared; actual source hashes retained below",
        "source_files_sha256": source_files,
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine(), "python": platform.python_version()},
        "runtime": versions,
        "builder": {"pyinstaller": PYINSTALLER_VERSION, "mode": "onedir", "device": "cpu"},
        "model": provenance,
        "license_inventory_scope": "installed build/runtime candidates; not an import inventory",
        "license_inventory": licenses,
        "integrity_scope": "SHA256 detects changed bytes; this manifest is not a publisher signature",
        "files": files,
    }
    (bundle / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output = args.output.resolve()
        if output.exists():
            raise ValueError(f"refusing to overwrite existing output: {output}")
        model_dir = args.model_dir.resolve(strict=True)
        root = Path(__file__).resolve().parents[3]
        extra_paths = [path.resolve(strict=True) for path in args.runtime_site_packages]
        for path in reversed(extra_paths):
            if not path.is_dir():
                raise ValueError("runtime-site-packages must be a directory")
            sys.path.insert(0, str(path))
        versions = validate_runtime()
        from rl.boss.release import load_release_descriptor, validate_frozen_artifact

        descriptor = load_release_descriptor()
        provenance = validate_frozen_artifact(model_dir / str(descriptor["model_file"]))
        plan = {"output": str(output), "model": provenance, "runtime": versions,
                "python": PYTHON_VERSION, "pyinstaller": PYINSTALLER_VERSION,
                "source_commit": args.source_commit}
        if args.plan:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        output.parent.mkdir(parents=True, exist_ok=True)
        work = output.parent / f".{output.name}.build-{uuid.uuid4().hex}"
        work.mkdir()
        staged_models = work / "models"
        staged_models.mkdir()
        for key in ("model_file", "selection_file", "training_file"):
            shutil.copyfile(model_dir / str(descriptor[key]), staged_models / str(descriptor[key]))
        command = pyinstaller_command(root, staged_models, work, extra_paths)
        subprocess.run(command, cwd=root, check=True)
        bundle = work / "dist" / APP_NAME
        licenses = collect_licenses(bundle / "third-party-licenses")
        sources = [*sorted((root / "rl/boss").glob("*.py")),
                   root / "rl/boss/deployment.json", Path(__file__).resolve(),
                   root / "scripts/rl/boss/release_entry.py"]
        source_files = {path.relative_to(root).as_posix(): file_sha256(path) for path in sources}
        write_manifest(bundle, provenance=provenance, versions=versions,
                       source_commit=args.source_commit, source_files=source_files, licenses=licenses)
        from scripts.rl.boss.release_entry import verify_bundle

        verify_bundle(bundle)
        if output.exists() or bundle.resolve().parent.parent != work.resolve():
            raise ValueError("unsafe build output move")
        bundle.rename(output)
        if (work.resolve().parent != output.parent.resolve()
                or not work.name.startswith(f".{output.name}.build-")):
            raise ValueError("unsafe build workspace cleanup")
        shutil.rmtree(work)
        print(json.dumps({"built": True, **plan}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, metadata.PackageNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Boss release build failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
