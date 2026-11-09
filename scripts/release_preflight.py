"""Release configuration preflight for the Aesir AI service.

This command is intentionally read-only.  It checks configuration gates that
must be true before staging or production deployment; it does not claim that
HTTPS, UE execution, external providers, backups, or capacity have passed.

Examples::

    python scripts/release_preflight.py --mode staging
    python scripts/release_preflight.py --mode production --json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings


@dataclass(frozen=True)
class Check:
    key: str
    status: str  # PASS, WARN, BLOCK
    message: str


def _secret_value(settings: Settings, field: str) -> str:
    value = getattr(settings, field)
    return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)


def _database_configured(settings: Settings) -> bool:
    direct = _secret_value(settings, "scope_database_url").strip()
    if direct:
        return True
    path = settings.scope_database_url_file.strip()
    return bool(path and Path(path).is_file() and Path(path).read_text(encoding="utf-8").strip())


def _llm_required(settings: Settings) -> bool:
    return any(
        backend == "llm"
        for backend in (settings.parser_backend, settings.companion_backend, settings.intent_backend)
    )


def run_preflight(mode: str, settings: Settings | None = None) -> list[Check]:
    """Return configuration checks without mutating files or contacting services."""

    settings = settings or get_settings()
    production = mode == "production"
    checks: list[Check] = []

    def add(key: str, ok: bool, message: str, *, warn: bool = False) -> None:
        checks.append(Check(key, "PASS" if ok else ("WARN" if warn else "BLOCK"), message))

    add(
        "identity",
        settings.scope_identity_backend == "bearer",
        "Bearer identity is enabled."
        if settings.scope_identity_backend == "bearer"
        else "scope_identity_backend must be bearer; development/disabled identity is not a release credential.",
    )
    add(
        "storage",
        settings.scope_storage_backend == "sql",
        "SQL scoped storage is enabled."
        if settings.scope_storage_backend == "sql"
        else "scope_storage_backend must be sql; JSON storage is development-only.",
    )
    add(
        "database_url",
        _database_configured(settings),
        "A database URL or readable database URL file is configured."
        if _database_configured(settings)
        else "No database URL or readable scope_database_url_file is configured.",
    )
    add(
        "coordination",
        settings.coordination_backend == "redis",
        "Redis coordination is enabled."
        if settings.coordination_backend == "redis"
        else "memory coordination is single-process only; use Redis for a release deployment.",
    )
    add(
        "legacy_routes",
        not settings.scope_legacy_enabled,
        "Legacy compatibility routes are disabled."
        if not settings.scope_legacy_enabled
        else "scope_legacy_enabled must be false for a release deployment.",
    )

    llm_ready = all(
        _secret_value(settings, field).strip()
        for field in ("llm_api_key", "llm_model", "llm_base_url")
    )
    add(
        "llm_credentials",
        llm_ready if _llm_required(settings) else True,
        "LLM credentials and endpoint are configured."
        if llm_ready or not _llm_required(settings)
        else "An LLM backend is selected but LLM_API_KEY, LLM_MODEL, or LLM_BASE_URL is missing.",
    )

    add(
        "asr_backend",
        settings.asr_backend != "mock",
        "A non-mock ASR backend is selected."
        if settings.asr_backend != "mock"
        else "mock ASR is enabled; voice acceptance cannot use this configuration.",
        warn=not production,
    )
    add(
        "https_boundary",
        False,
        "The app is bound to loopback; an external HTTPS reverse proxy must be verified separately."
        if settings.service_host in {"127.0.0.1", "localhost", "::1"}
        else "The app is not bound to loopback; verify firewall and TLS termination before exposure.",
        warn=True,
    )
    add(
        "mode_note",
        True,
        "This preflight does not verify UE execution, HTTPS certificates, backups, restore, capacity, or provider health.",
    )
    return checks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only release configuration preflight")
    parser.add_argument("--mode", choices=("staging", "production"), required=True)
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        checks = run_preflight(args.mode)
    except Exception as exc:  # configuration parsing itself is a release blocker
        payload: dict[str, Any] = {
            "mode": args.mode,
            "checks": [asdict(Check("configuration", "BLOCK", f"Configuration could not be loaded: {exc}"))],
        }
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"BLOCK configuration: {exc}")
        return 1

    payload = {"mode": args.mode, "checks": [asdict(check) for check in checks]}
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            print(f"{check.status:5} {check.key}: {check.message}")

    return 1 if any(check.status == "BLOCK" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
