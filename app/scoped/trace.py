"""Metadata-only, best-effort request/transport tracing; no player text or keys."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from threading import RLock
import time
from uuid import uuid4

from app.config import get_settings
from app.scoped.storage import signal_directory, signal_metadata

_trace = ContextVar("scoped_transport_trace", default=None)
_lock = RLock()
_logger = logging.getLogger(__name__)


def record_trace(event, **fields):
    context = _trace.get()
    if context is None:
        return
    try:
        row = {"recorded_at": datetime.now(timezone.utc).isoformat(), "event": event,
               **signal_metadata(), **context, **fields}
        path = signal_directory(get_settings().request_traces_dir, context["game_id"]) / "requests.jsonl"
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        # A diagnostic log is not a business commit acknowledgement.
        _logger.warning("Request metadata trace could not be written")


@contextmanager
def request_trace(scope, operation, request_id):
    token = _trace.set({"game_id": scope.npc.game_id, "operation": operation,
                        "logical_request_id": str(request_id), "http_attempt_id": str(uuid4())})
    started = time.monotonic()
    outcome, reason = "returned", None
    try:
        yield
    except Exception as error:
        outcome, reason = "rejected", getattr(error, "code", "REQUEST_FAILED")
        raise
    finally:
        record_trace("http_attempt_finished", outcome=outcome, reason_code=reason,
                     elapsed_ms=max(0, int((time.monotonic() - started) * 1000)))
        _trace.reset(token)
