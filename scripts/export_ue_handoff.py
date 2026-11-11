"""Export an offline UE interface bundle; no HTTP, model or database calls.

Run from the project root: python -m scripts.export_ue_handoff
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "docs/examples/ue-scoped.http",
    "docs/guides/ue-service-adaptation.md",
    "docs/guides/asr-self-hosted.md",
    "docs/guides/scoped-development.md",
    "docs/guides/persistent-development.md",
    "docs/guides/deployment.md",
    "docs/protocols/npc-scope-contract-v0.4-draft.md",
    "docs/protocols/npc-loop-contract-v0.4.md",
    "docs/protocols/npc-async-loop-v0.5-draft.md",
    "docs/protocols/npc-persistence-contract-v0.4.md",
    "deploy/README.md",
    "deploy/aesir-ai.service",
    "deploy/service.env.example",
    "deploy/nginx-aesir.conf",
)


def _revision():
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                         stderr=subprocess.DEVNULL, text=True).strip()
        changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT,
                                  stderr=subprocess.DEVNULL).returncode != 0
        return commit, changed
    except (OSError, subprocess.CalledProcessError):
        return None, None


def export(destination: Path) -> Path:
    # Importing FastAPI's application builds its schema; lifespan is never entered.
    from app.main import app

    files = {name: (ROOT / name).read_bytes() for name in FILES}
    files["openapi.json"] = (json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    commit, changed = _revision()
    manifest = {
        "service_commit": commit,
        "tracked_worktree_modified": changed,
        "evidence_level": "offline-source-export-not-runtime-acceptance",
        "sample_identifiers": "placeholders-replace-from-current-context-and-bind",
        "files": {name: {"bytes": len(body), "sha256": sha256(body).hexdigest()}
                  for name, body in sorted(files.items())},
    }
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    files["START-HERE.txt"] = (
        "Aesir UE service handoff\n\n"
        "Read docs/guides/ue-service-adaptation.md first.\n"
        "Request examples: docs/examples/ue-scoped.http\n"
        "Machine-readable contract: openapi.json\n"
        "Deployment preparation: deploy/README.md\n\n"
        "This bundle contains source-derived contracts, not runtime evidence.\n"
        "All sample IDs are placeholders. Discover context and bind a fresh run.\n"
        "Keep real Bearer tokens in a private HTTP-client environment.\n"
        "No private environment, audio, memory, model weights or runtime logs are included.\n"
        "Historical notes in included guides do not override the current source schema.\n"
        "See manifest.json for the code revision, worktree state and file hashes.\n"
    ).encode("utf-8")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "ue-service-handoff.zip"
    # Write a separate temporary archive so an export failure preserves the previous bundle.
    temporary = destination / "ue-service-handoff.zip.tmp"
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as bundle:
        for name, body in sorted(files.items()):
            bundle.writestr(name, body)
    temporary.replace(archive)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/runtime/ue-handoff")
    args = parser.parse_args()
    archive = export(args.output_dir)
    print(json.dumps({"archive": str(archive), "sha256": sha256(archive.read_bytes()).hexdigest(),
                      "runtime_verification_performed": False}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
