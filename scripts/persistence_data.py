"""Explicit scoped SQL migration and private logical backup/restore commands."""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
from importlib import import_module
import json
import os
import stat
from pathlib import Path
from uuid import UUID

from sqlalchemy import Date, DateTime, LargeBinary, Numeric, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.persistence.database import checked_namespace, get_database, parts_hash, unavailable
from app.persistence.schema import SCHEMA_VERSION, documents, metadata, schema_versions, state_versions
from app.scoped.context import safe_segment
from app.scoped.errors import ScopeError
from app.schemas.memory import MemorySnapshot
from app.schemas.relationship import RelationshipState


def _load_tables():
    for module in ("app.persistence.auth", "app.persistence.journal"):
        try:
            import_module(module)
        except ModuleNotFoundError as error:
            if error.name != module:
                raise


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_sources(memory_root, relationship_root):
    """Validate owned scoped files without editing or claiming legacy data."""
    records, excluded = [], []
    for kind, root, filename in (("memory", Path(memory_root), "memory.json"),
                                  ("relationship", Path(relationship_root), "relationship.json")):
        if not root.exists():
            continue
        resolved_root = root.resolve()
        for path in sorted(root.rglob(filename)):
            relative = path.relative_to(root)
            parts = relative.parts
            if len(parts) != 5:
                excluded.append(str(relative))
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(resolved_root):
                raise ValueError("A migration source escapes its configured root")
            game, player, save, npc, _ = parts
            key = (safe_segment(game), str(UUID(player)), str(UUID(save)), safe_segment(npc))
            raw = path.read_bytes()
            data = json.loads(raw)
            if kind == "memory":
                if set(data) != {"memory_epoch", "short_term", "summaries", "archive", "impressions"}:
                    raise ValueError("Memory source must include its complete scoped epoch document")
                epoch = str(UUID(data["memory_epoch"]))
                snapshot = MemorySnapshot.model_validate(data)
                payload = {"memory_epoch": epoch, **snapshot.model_dump(mode="json")}
            else:
                if isinstance(data.get("value"), bool) or not isinstance(data.get("value"), int) or not 0 <= data["value"] <= 100:
                    raise ValueError("Relationship source value is invalid")
                payload = RelationshipState.model_validate(data).model_dump(mode="json")
            records.append(dict(namespace=kind, key=key, payload=payload, path=path,
                                source_sha256=hashlib.sha256(raw).hexdigest()))
    identities = [(row["namespace"], row["key"]) for row in records]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate scoped migration identity")
    return records, excluded


def import_json(database, memory_root, relationship_root, *, apply=False):
    records, excluded = scan_sources(memory_root, relationship_root)
    report = {"mode": "apply" if apply else "dry-run", "sources": [
        {"namespace": row["namespace"], "scope": list(row["key"]), "sha256": row["source_sha256"]}
        for row in records], "excluded_unowned": excluded, "imported": 0, "unchanged": 0}
    if not apply:
        return report
    database.check_schema()
    for row in records:
        if _file_hash(row["path"]) != row["source_sha256"]:
            raise ValueError("Migration source changed after validation")
    changed_scopes = set()
    try:
        with database.engine.begin() as connection:
            for row in records:
                key, namespace = row["key"], row["namespace"]
                existing = connection.execute(select(documents).where(documents.c.namespace == namespace,
                    documents.c.key_hash == parts_hash(key)).with_for_update()).mappings().one_or_none()
                if existing is not None:
                    if tuple(existing["key_parts"]) != key or existing["payload"] != row["payload"]:
                        raise ScopeError(409, "MIGRATION_CONFLICT", "An existing scoped document differs from the migration source")
                    report["unchanged"] += 1
                    continue
                connection.execute(insert(documents).values(namespace=namespace, key_hash=parts_hash(key),
                    key_parts=list(key), scope_parts=list(key), payload=row["payload"], version=1))
                changed_scopes.add(key)
                report["imported"] += 1
            for scope in sorted(changed_scopes):
                row = connection.execute(select(state_versions).where(state_versions.c.scope_hash == parts_hash(scope)).with_for_update()).mappings().one_or_none()
                if row is None:
                    connection.execute(insert(state_versions).values(scope_hash=parts_hash(scope), scope_parts=list(scope), version=1))
                else:
                    connection.execute(update(state_versions).where(state_versions.c.scope_hash == parts_hash(scope)).values(version=row["version"] + 1))
    except SQLAlchemyError as error:
        raise unavailable() from error
    return report


def _encode_sql(value):
    if isinstance(value, (datetime, date)):
        return {"$sql_type": "iso", "$value": value.isoformat()}
    if isinstance(value, bytes):
        return {"$sql_type": "bytes", "$value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return {"$sql_type": "decimal", "$value": str(value)}
    return value


def _decode_sql(column, value):
    if value is None:
        return None
    if isinstance(column.type, (DateTime, Date)):
        raw = value["$value"] if isinstance(value, dict) else value
        return datetime.fromisoformat(raw) if isinstance(column.type, DateTime) else date.fromisoformat(raw)
    if isinstance(column.type, LargeBinary):
        return base64.b64decode(value["$value"], validate=True)
    if isinstance(column.type, Numeric) and isinstance(value, dict):
        return Decimal(value["$value"])
    return value


def _private_output(path, payload):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("Backup output must be an absolute private path")
    # The checkout lives under a web server root. Keep complete data backups out.
    checkout = Path(__file__).resolve().parents[1]
    if path.resolve().is_relative_to(checkout) or (os.name == "posix" and path.resolve().is_relative_to(Path("/www/wwwroot"))):
        raise ValueError("Backups must be stored outside the application web directory")
    if os.name == "posix" and stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise ValueError("Backup parent directory must be private")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def backup_database(database, output):
    _load_tables()
    database.check_schema()
    data = {}
    try:
        with database.engine.connect() as connection:
            if database.engine.dialect.name == "mysql":
                connection = connection.execution_options(isolation_level="REPEATABLE READ")
            with connection.begin():
                if database.engine.dialect.name == "sqlite":
                    connection.exec_driver_sql("BEGIN")
                for table in metadata.sorted_tables:
                    rows = connection.execute(select(table)).mappings().all()
                    data[table.name] = [{key: _encode_sql(value) for key, value in row.items()} for row in rows]
    except SQLAlchemyError as error:
        raise unavailable() from error
    payload = {"format_version": 1, "schema_version": SCHEMA_VERSION,
               "created_utc": datetime.now(timezone.utc).isoformat(), "tables": data}
    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    _private_output(output, json.dumps({"sha256": digest, "payload": payload}, ensure_ascii=False, indent=2, allow_nan=False))
    return {"sha256": digest, "table_counts": {name: len(rows) for name, rows in data.items()}}


def _read_backup(source):
    envelope = json.loads(Path(source).read_text(encoding="utf-8"))
    payload = envelope["payload"]
    actual = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if actual != envelope["sha256"]:
        raise ValueError("Backup checksum does not match")
    if payload["format_version"] != 1 or payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Backup schema version is unsupported")
    _load_tables()
    if set(payload["tables"]) != set(metadata.tables):
        raise ValueError("Backup application table set is incomplete or unexpected")
    converted = {}
    for table in metadata.sorted_tables:
        converted[table.name] = []
        for row in payload["tables"][table.name]:
            if set(row) != set(table.c.keys()):
                raise ValueError("Backup row fields differ from schema")
            converted[table.name].append({column.name: _decode_sql(column, row[column.name]) for column in table.c})
    if converted["schema_versions"] != [{"id": 1, "version": SCHEMA_VERSION}]:
        raise ValueError("Backup schema marker is invalid")
    for row in converted["documents"]:
        checked_namespace(row["namespace"])
        if parts_hash(row["key_parts"]) != row["key_hash"] or row["version"] < 1 or not isinstance(row["payload"], dict):
            raise ValueError("Backup document identity is invalid")
    for row in converted["state_versions"]:
        if parts_hash(row["scope_parts"]) != row["scope_hash"] or row["version"] < 1:
            raise ValueError("Backup state identity is invalid")
    return converted


def restore_database(database, source, *, apply=False):
    data = _read_backup(source)
    # A backup can predate a credential revocation. Never reactivate old
    # bearer secrets merely because an operator restores an older snapshot.
    # Keep source bytes intact; new credentials require explicit reissuance.
    credentials_count = len(data.get("access_credentials", []))
    for credential in data.get("access_credentials", []):
        credential["revoked"] = True
    database.check_schema()
    try:
        with database.engine.begin() as connection:
            for table in metadata.sorted_tables:
                if table.name != "schema_versions" and connection.execute(select(func.count()).select_from(table)).scalar_one():
                    raise ScopeError(409, "RESTORE_TARGET_NOT_EMPTY", "Restore requires an empty isolated application database")
            if apply:
                for table in metadata.sorted_tables:
                    rows = data[table.name]
                    if table.name != "schema_versions" and rows:
                        connection.execute(insert(table), rows)
    except SQLAlchemyError as error:
        raise unavailable() from error
    return {"mode": "apply" if apply else "dry-run", "table_counts": {name: len(rows) for name, rows in data.items()},
            "credential_policy": "revoke_all_restored", "credentials_to_revoke": credentials_count,
            "credentials_revoked": credentials_count if apply else 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicit scoped SQL migration and backup operations")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--apply", action="store_true")
    importing = commands.add_parser("import-json")
    importing.add_argument("--memory-root", default=get_settings().memory_root)
    importing.add_argument("--relationship-root", default=get_settings().relationship_root)
    importing.add_argument("--apply", action="store_true")
    backup = commands.add_parser("backup")
    backup.add_argument("--output", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--input", required=True)
    restore.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            database = get_database()
            if args.apply:
                database.initialize_schema()
            result = {"mode": "apply" if args.apply else "dry-run", "schema_version": SCHEMA_VERSION}
        elif args.command == "import-json":
            database = get_database() if args.apply else None
            result = import_json(database, args.memory_root, args.relationship_root, apply=args.apply)
        elif args.command == "backup":
            result = backup_database(get_database(), args.output)
        else:
            result = restore_database(get_database(), args.input, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ScopeError as error:
        print(json.dumps({"error": error.code, "message": error.message}))
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"error": "MIGRATION_INPUT_INVALID", "message": "Migration input, private output, or backup validation failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
