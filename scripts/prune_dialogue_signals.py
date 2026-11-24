"""Dry-run by default: prune aged rotated dialogue archives, never active files."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

_ARCHIVE = re.compile(r'^companion\.[A-Za-z0-9_.-]+\.archive-\d{8}T\d{6}Z-[a-f0-9]{32}\.jsonl$')


def prune(root, days, *, apply=False, now=None):
    if days < 1:
        raise ValueError('retention must be at least one day')
    root = root.resolve()
    cutoff = (now or datetime.now(timezone.utc)).timestamp() - days*86400
    candidates = []
    for path in root.rglob('*.jsonl'):
        if (not path.is_symlink() and _ARCHIVE.fullmatch(path.name)
                and path.resolve().is_relative_to(root) and path.stat().st_mtime < cutoff):
            candidates.append(path)
    report = dict(mode='apply' if apply else 'dry-run', candidates=len(candidates),
                  bytes=sum(path.stat().st_size for path in candidates),deleted=0,retention_days=days)
    if apply:
        for path in candidates:
            # Recheck the resolved file before deletion; do not follow links.
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Archive target changed outside root')
            path.unlink()
            report['deleted'] += 1
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--older-than-days',type=int,default=30)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(prune(args.root,args.older_than_days,apply=args.apply)))


if __name__=='__main__':
    main()
