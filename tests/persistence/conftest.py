"""SQLite is an explicit isolated-test backend, never a deployed fallback."""
import pytest


@pytest.fixture(autouse=True)
def allow_isolated_sqlite(monkeypatch):
    monkeypatch.setenv("AESIR_SCOPE_SQLITE_TEST_MODE", "true")
