"""Short SQL transactions and canonical document identities; no DSNs in errors."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from importlib import import_module
from pathlib import Path
import os
import stat
from threading import RLock

from sqlalchemy import Double, create_engine, event, insert, inspect, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.scoped.errors import ScopeError
from app.persistence.schema import SCHEMA_VERSION, documents, metadata, schema_versions, state_versions


def unavailable():
    return ScopeError(503, "STATE_UNAVAILABLE", "SQL application state is unavailable")


def conflict():
    return ScopeError(409, "STATE_VERSION_CONFLICT", "State changed before the transaction could commit")


def canonical_parts(parts):
    return tuple(str(value) for value in parts)


def parts_hash(parts):
    raw = json.dumps(canonical_parts(parts), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def checked_namespace(namespace):
    if not isinstance(namespace, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", namespace):
        raise ValueError("Invalid document namespace")
    return namespace


def json_copy(payload):
    if not isinstance(payload, dict):
        raise ValueError("Document payload must be an object")
    return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))


class Database:
    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def from_url(cls, url):
        parsed = make_url(url)
        if parsed.drivername not in {"sqlite", "sqlite+pysqlite", "mysql+pymysql"}:
            raise ValueError("Only MySQL/PyMySQL and isolated SQLite are supported")
        options = {"pool_pre_ping": True}
        if parsed.drivername.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 15}
            if parsed.database in {None, "", ":memory:"}:
                raise ValueError("SQLite persistence tests require an isolated file database")
        else:
            options["pool_size"] = getattr(get_settings(), "scope_database_pool_size", 5)
            options["max_overflow"] = 0
        engine = create_engine(parsed, **options)
        if parsed.drivername.startswith("sqlite"):
            @event.listens_for(engine, "connect")
            def sqlite_settings(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=15000")
                connection.execute("PRAGMA journal_mode=WAL")
        return cls(engine)

    def initialize_schema(self):
        """Explicit operator command only; uses a separate migration account."""
        # Import optional application table declarations before explicit DDL.
        for module in ("app.persistence.auth", "app.persistence.journal"):
            try:
                import_module(module)
            except ModuleNotFoundError as error:
                if error.name != module:
                    raise
        try:
            self._check_server_version()
            metadata.create_all(self.engine)
            with self.engine.begin() as connection:
                version = connection.execute(select(schema_versions.c.version).where(schema_versions.c.id == 1)).scalar_one_or_none()
                if version is None:
                    connection.execute(insert(schema_versions).values(id=1, version=SCHEMA_VERSION))
                elif version != SCHEMA_VERSION:
                    raise unavailable()
            self.check_schema()
        except SQLAlchemyError as error:
            raise unavailable() from error

    def _check_server_version(self):
        if self.engine.dialect.name == "mysql":
            with self.engine.connect():
                version = self.engine.dialect.server_version_info
                if getattr(self.engine.dialect, "is_mariadb", False) or not version or version < (8, 4):
                    raise ScopeError(503, "DATABASE_VERSION_UNSUPPORTED", "A supported MySQL LTS application database is required")

    def check_schema(self):
        try:
            self._check_server_version()
            with self.engine.connect() as connection:
                version = connection.execute(select(schema_versions.c.version).where(schema_versions.c.id == 1)).scalar_one_or_none()
                if version != SCHEMA_VERSION:
                    raise unavailable()
                for table in metadata.sorted_tables:
                    connection.execute(select(table).limit(0))
                if self.engine.dialect.name == "mysql":
                    inspector = inspect(connection)
                    for table in metadata.sorted_tables:
                        doubles = {column.name for column in table.c if isinstance(column.type, Double)}
                        if not doubles:
                            continue
                        actual = {column["name"]: column["type"] for column in inspector.get_columns(table.name)}
                        if any(actual[name].__class__.__name__.upper() != "DOUBLE" for name in doubles):
                            raise ScopeError(503, "DATABASE_SCHEMA_MISMATCH", "Application schema requires full precision timestamp columns")
        except SQLAlchemyError as error:
            raise unavailable() from error

    def _read(self, namespace, key):
        namespace, key = checked_namespace(namespace), canonical_parts(key)
        try:
            with self.engine.connect() as connection:
                row = connection.execute(select(documents).where(
                    documents.c.namespace == namespace, documents.c.key_hash == parts_hash(key),
                )).mappings().one_or_none()
            if row is not None and tuple(row["key_parts"]) != key:
                raise unavailable()
            return row
        except SQLAlchemyError as error:
            raise unavailable() from error

    def read_document(self, namespace, key, default=None):
        from app.persistence.uow import current_uow
        unit = current_uow()
        if unit is not None:
            value = unit.read_document(namespace, key)
            return deepcopy(default) if value is None else value
        row = self._read(namespace, key)
        return deepcopy(row["payload"]) if row else deepcopy(default)

    def write_document(self, namespace, key, payload, *, scope_parts=()):
        from app.persistence.uow import current_uow, use_unit_of_work
        unit = current_uow()
        if unit is not None:
            unit.write_document(namespace, key, payload, scope_parts=scope_parts)
        else:
            with use_unit_of_work(scope_parts, database=self) as unit:
                unit.write_document(namespace, key, payload, scope_parts=scope_parts)
                unit.commit()

    def delete_document(self, namespace, key, *, scope_parts=()):
        from app.persistence.uow import current_uow, use_unit_of_work
        unit = current_uow()
        if unit is not None:
            unit.delete_document(namespace, key, scope_parts=scope_parts)
        else:
            with use_unit_of_work(scope_parts, database=self) as unit:
                unit.delete_document(namespace, key, scope_parts=scope_parts)
                unit.commit()

    def list_documents(self, namespace, scope_parts=()):
        from app.persistence.uow import current_uow
        namespace, prefix = checked_namespace(namespace), canonical_parts(scope_parts)
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(select(documents).where(documents.c.namespace == namespace)).mappings().all()
            found = {tuple(row["key_parts"]): deepcopy(row["payload"]) for row in rows
                     if tuple(row["scope_parts"][:len(prefix)]) == prefix}
            unit = current_uow()
            if unit is not None:
                unit.overlay_listing(namespace, prefix, found)
            return sorted(found.items(), key=lambda item: item[0])
        except SQLAlchemyError as error:
            raise unavailable() from error

    def state_version(self, scope_parts):
        parts = canonical_parts(scope_parts)
        try:
            with self.engine.connect() as connection:
                row = connection.execute(select(state_versions).where(state_versions.c.scope_hash == parts_hash(parts))).mappings().one_or_none()
            if row is not None and tuple(row["scope_parts"]) != parts:
                raise unavailable()
            return row["version"] if row else 0
        except SQLAlchemyError as error:
            raise unavailable() from error


_database = None
_database_url = None
_database_lock = RLock()


def database_enabled():
    return getattr(get_settings(), "scope_storage_backend", "json") == "sql"


def get_database():
    global _database, _database_url
    settings = get_settings()
    file = getattr(settings, "scope_database_url_file", "")
    try:
        if file:
            path = Path(file)
            if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise unavailable()
            url = path.read_text(encoding="utf-8").strip()
        else:
            secret = getattr(settings, "scope_database_url", None)
            url = secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
    except OSError as error:
        raise unavailable() from error
    with _database_lock:
        if _database is not None and _database_url is None:
            return _database
        if not url:
            raise unavailable()
        if _database is None or _database_url != url:
            if _database is not None:
                _database.engine.dispose()
            try:
                if make_url(url).drivername.startswith("sqlite") and not getattr(settings, "scope_sqlite_test_mode", False):
                    raise ValueError("SQLite is available only in explicit persistence test mode")
                _database = Database.from_url(url)
            except (ValueError, SQLAlchemyError) as error:
                raise unavailable() from error
            _database_url = url
        return _database


def reset_database(database=None):
    global _database, _database_url
    with _database_lock:
        if _database is not None and _database is not database:
            _database.engine.dispose()
        _database, _database_url = database, None
    return database


def read_document(namespace, key, default=None):
    return get_database().read_document(namespace, key, default)


def write_document(namespace, key, payload, *, scope_parts=()):
    return get_database().write_document(namespace, key, payload, scope_parts=scope_parts)


def delete_document(namespace, key, *, scope_parts=()):
    return get_database().delete_document(namespace, key, scope_parts=scope_parts)


def list_documents(namespace, scope_parts=()):
    return get_database().list_documents(namespace, scope_parts)


def state_version(scope_parts):
    return get_database().state_version(scope_parts)
