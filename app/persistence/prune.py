"""Operator-initiated retention pruning for high-growth ledger tables.

These tables grow one row per player-minute (access_quotas window rows) or per
request (operation_journal terminal rows). Nothing in the service auto-prunes
them: cleanup is an explicit operator action so retention policy stays visible
and auditable. Running journal rows (state='running') are never touched — they
are in-flight claims, not garbage.

Cutoffs are epoch seconds (time.time()). A row is pruned only when it is in a
terminal state AND its finishing timestamp is older than the cutoff.
"""
from __future__ import annotations

import time

from sqlalchemy import delete

from app.persistence.database import get_database, unavailable
from app.persistence.journal import operations
from app.persistence.auth import quota_usage

# Terminal journal states safe to forget once finished long ago. 'running' is
# deliberately excluded: an unfinished claim belongs to an in-flight (or
# crashed) request and must remain recoverable, not be pruned.
_TERMINAL_JOURNAL_STATES = ("complete", "failed", "unknown")


def prune_journal(*, cutoff_seconds: float | None = None) -> int:
    """Delete terminal operation_journal rows finished before the cutoff.

    Returns the number of rows deleted. Running rows are always preserved.
    """
    if cutoff_seconds is None:
        cutoff_seconds = time.time()
    try:
        with get_database().engine.begin() as connection:
            result = connection.execute(delete(operations).where(
                operations.c.state.in_(_TERMINAL_JOURNAL_STATES),
                operations.c.finished_at.is_not(None),
                operations.c.finished_at < cutoff_seconds,
            ))
        return int(result.rowcount or 0)
    except Exception as error:  # SQLAlchemyError surface, never leak DSNs
        raise unavailable() from error


def prune_quota_windows(*, cutoff_seconds: float | None = None) -> int:
    """Delete access_quotas window rows older than the cutoff.

    Quota reservations are admission control for a recent rolling window; old
    window rows no longer gate anything once their window_start is stale.
    Returns the number of rows deleted.
    """
    if cutoff_seconds is None:
        cutoff_seconds = time.time()
    try:
        with get_database().engine.begin() as connection:
            result = connection.execute(delete(quota_usage).where(
                quota_usage.c.window_start < cutoff_seconds,
            ))
        return int(result.rowcount or 0)
    except Exception as error:
        raise unavailable() from error
