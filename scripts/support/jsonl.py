"""Read legacy and nested scoped JSONL signals; skip unreadable/invalid records."""
import json
from pathlib import Path

def iter_records(root: Path):
    for path in sorted(root.rglob("*.jsonl")):
        try:
            with path.open(encoding="utf-8") as source:
                for line in source:
                    try:
                        value = json.loads(line)
                    except (ValueError, RecursionError):
                        continue
                    if isinstance(value, dict):
                        yield path, value
        except (OSError, UnicodeError):
            continue
