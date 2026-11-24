"""Size rotation for dialogue signals only; never touch authority ledgers."""
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
from app.scoped.storage import append_jsonl

_lock = RLock()


def write_signal(root, filename, payload, max_bytes):
    path = Path(root)/filename
    with _lock:
        if path.exists() and path.stat().st_size + len(payload.encode('utf-8'))+1 > max_bytes:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            path.rename(path.with_name(f'{path.stem}.archive-{stamp}-{uuid4().hex}.jsonl'))
        append_jsonl(root, filename, payload)
