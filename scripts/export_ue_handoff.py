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
    "docs/records/_08_project_functionality_assessment.md",
    "docs/records/data/project-assessment-20261118.json",
    "docs/records/data/memory-forget-live-20261118.json",
    "docs/records/data/memory-model-eval-20261118.json",
    "docs/records/data/dialogue-data-quality-20261118.json",
    "data/golden/memory/forget_request.json",
    "data/golden/memory/forget_response.json",
    "data/golden/memory/entries_response.json",
    "docs/guides/_13_service_handoff_guide.md",
    "docs/records/_07_p0_closure_verification.md",
    "docs/records/data/p0-closure-20261118.json",
    "docs/guides/_02_local_setup_guide.md",
    "docs/guides/_03_llm_integration_guide.md",
    "docs/guides/_08_remote_development_guide.md",
    "docs/records/_03_p0_delivery_verification.md",
    "docs/records/_04_prompt_grounding_verification.md",
    "docs/records/_05_p1_server_verification.md",
    "docs/records/_06_issue_audit_verification.md",
    "docs/records/data/prompt-grounding-20261116.json",
    "docs/records/data/p1-server-20261116.json",
    "docs/records/data/p1-server-20261118.json",
    "docs/records/data/memory-retrieval-20261118.json",
    "docs/records/data/issue-audit-20261118.json",
    "docs/examples/ue-scoped.http",
    "docs/guides/_05_client_integration_guide.md",
    "docs/guides/_11_asr_guide.md",
    "docs/guides/_04_scoped_development_guide.md",
    "docs/guides/_06_persistence_guide.md",
    "docs/guides/_07_deployment_guide.md",
    "docs/protocols/_01_npc_contract.md",
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
        "Read docs/guides/_13_service_handoff_guide.md first.\n"
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
