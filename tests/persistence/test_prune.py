"""Operator retention pruning: terminal journal rows and stale quota windows."""
import time
from uuid import uuid4

import pytest
from sqlalchemy import insert, select

from app.persistence.auth import quota_usage
from app.persistence.database import Database, reset_database
from app.persistence.journal import operations
from app.persistence import prune


@pytest.fixture
def sql(tmp_path):
    database = Database.from_url("sqlite:///" + str(tmp_path / "prune.sqlite"))
    database.initialize_schema()
    reset_database(database)
    yield database
    reset_database()


def _insert_journal_row(database, *, state, finished_age):
    old = time.time() - finished_age
    with database.engine.begin() as connection:
        connection.execute(insert(operations).values(
            identity_hash=uuid4().hex, kind="request", key_parts=["a"],
            scope_parts=["a"], request_id=str(uuid4()), fingerprint="fp",
            owner_instance="worker-x", state=state,
            created_at=old, finished_at=old if state != "running" else None,
        ))


def _insert_quota_row(database, *, age):
    with database.engine.begin() as connection:
        connection.execute(insert(quota_usage).values(
            game_id="aesir", player_id=str(uuid4()), kind="request",
            window_start=int(time.time() - age), used=1,
        ))


def count(database, table):
    from sqlalchemy import func
    with database.engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(table)).scalar_one()


def test_prune_june_terminal_rows_older_than_cutoff(sql):
    _insert_journal_row(sql, state="complete", finished_age=40 * 86400)  # 40d
    _insert_journal_row(sql, state="failed", finished_age=35 * 86400)    # 35d
    _insert_journal_row(sql, state="complete", finished_age=5 * 86400)   # 5d keep
    removed = prune.prune_journal(cutoff_seconds=time.time() - 30 * 86400)
    assert removed == 2
    assert count(sql, operations) == 1


def test_prune_journal_never_touches_running_rows(sql):
    _insert_journal_row(sql, state="running", finished_age=0)  # no finished_at
    _insert_journal_row(sql, state="running", finished_age=999 * 86400)
    removed = prune.prune_journal(cutoff_seconds=time.time())
    assert removed == 0
    assert count(sql, operations) == 2


def test_prune_quota_windows_older_than_cutoff(sql):
    _insert_quota_row(sql, age=10 * 86400)  # 10d
    _insert_quota_row(sql, age=2 * 86400)   # 2d keep
    removed = prune.prune_quota_windows(cutoff_seconds=time.time() - 7 * 86400)
    assert removed == 1
    assert count(sql, quota_usage) == 1


def test_prune_default_cutoff_is_now_deletes_all_terminal_rows(sql):
    # Default cutoff = time.time(), so any already-finished row (finished_at < now)
    # is eligible. The CLI only makes this safe by passing an age-based cutoff.
    _insert_journal_row(sql, state="complete", finished_age=10)  # 10s ago
    _insert_journal_row(sql, state="running", finished_age=0)  # in-flight, kept
    assert prune.prune_journal() == 1
    assert count(sql, operations) == 1
    assert count(sql, quota_usage) == 0
