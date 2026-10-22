"""Generation commit and upstream boundaries shared by existing business code."""
from functools import wraps
import time

from app.scoped.requests import final_commit, upstream_attempt
from app.scoped.trace import record_trace


def final_generation_commit(function):
    @wraps(function)
    def committed(*args, **kwargs):
        # Caller first holds the established runtime/NPC commit_guard locks.
        with final_commit():
            return function(*args, **kwargs)
    return committed


def scoped_upstream(function):
    @wraps(function)
    def attempted(*args, **kwargs):
        from app.persistence.database import database_enabled
        from app.scoped.requests import has_active_request, timeout_for_upstream
        if database_enabled() and has_active_request():
            # Reject stale/cancelled work before reserving a daily provider call;
            # quota failures must not count as an actual upstream attempt.
            timeout_for_upstream(float("inf"))
            from app.persistence.auth import reserve_upstream_quota
            reserve_upstream_quota()
        with upstream_attempt() as attempt_id:
            started = time.monotonic()
            outcome = "returned"
            record_trace("upstream_started", upstream_attempt_id=attempt_id)
            try:
                return function(*args, **kwargs)
            except Exception:
                outcome = "failed"
                raise
            finally:
                record_trace("upstream_finished", upstream_attempt_id=attempt_id, outcome=outcome,
                             elapsed_ms=max(0, int((time.monotonic() - started) * 1000)))
    return attempted
