from __future__ import annotations

from pathlib import Path

from app.config import Settings
from scripts.release_preflight import run_preflight


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "scope_identity_backend": "bearer",
        "scope_storage_backend": "sql",
        "scope_database_url": "mysql://aesir:test@db/aesir",
        "coordination_backend": "redis",
        "scope_legacy_enabled": False,
        "asr_backend": "faster_whisper",
        "parser_backend": "llm",
        "companion_backend": "llm",
        "intent_backend": "llm",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
        "llm_base_url": "https://llm.example/v1",
    }
    values.update(overrides)
    return Settings(**values)


def _by_key(checks):
    return {check.key: check for check in checks}


def test_release_preflight_passes_configuration_gates(tmp_path: Path) -> None:
    checks = _by_key(run_preflight("production", _settings(tmp_path)))
    assert all(checks[key].status == "PASS" for key in (
        "identity", "storage", "database_url", "coordination", "legacy_routes", "llm_credentials", "asr_backend"
    ))
    assert checks["https_boundary"].status == "WARN"


def test_production_blocks_dev_identity_json_memory_and_mock_asr(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        scope_identity_backend="development",
        scope_storage_backend="json",
        scope_database_url="",
        coordination_backend="memory",
        asr_backend="mock",
    )
    checks = _by_key(run_preflight("production", settings))
    assert all(checks[key].status == "BLOCK" for key in (
        "identity", "storage", "database_url", "coordination", "asr_backend"
    ))


def test_staging_allows_mock_asr_as_explicit_warning(tmp_path: Path) -> None:
    settings = _settings(tmp_path, asr_backend="mock")
    checks = _by_key(run_preflight("staging", settings))
    assert checks["asr_backend"].status == "WARN"


def test_external_asr_requires_a_readable_nonempty_speech_credential(tmp_path: Path) -> None:
    key = tmp_path / "speech-key"
    key.write_text("", encoding="utf-8")
    settings = _settings(tmp_path, asr_backend="volcengine", asr_volc_api_key="",
                         asr_volc_api_key_file=str(key))
    assert _by_key(run_preflight("production", settings))["asr_credentials"].status == "BLOCK"
    key.write_text("speech-test-key", encoding="utf-8")
    assert _by_key(run_preflight("production", settings))["asr_credentials"].status == "PASS"


def test_unknown_asr_backend_does_not_pass_release_gates(tmp_path: Path) -> None:
    settings = _settings(tmp_path, asr_backend="misspelled")
    assert _by_key(run_preflight("staging", settings))["asr_backend"].status == "BLOCK"
