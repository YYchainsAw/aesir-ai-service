"""Database-backed opaque credentials and independent admission reservations.

Bearer secrets never enter the database. Quota reservations commit separately
from business effects so an already issued provider call cannot be refunded by
cancellation, rollback or process restart.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import math
import re
import secrets
import time
from uuid import UUID, uuid4

from sqlalchemy import (Boolean, Column, Double, ForeignKeyConstraint, Integer,
                        String, Table, BigInteger, select, insert, update)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import get_settings
from app.persistence.database import database_enabled, get_database
from app.persistence.schema import metadata
from app.scoped.context import current_scope, safe_segment
from app.scoped.errors import ScopeError

PERMISSIONS = frozenset({"npc:use", "console:read", "memory:reset", "docs:read"})
DEVELOPMENT_PERMISSIONS = PERMISSIONS

players = Table(
    "access_players", metadata,
    Column("game_id", String(100), primary_key=True),
    Column("player_id", String(36), primary_key=True),
    Column("active", Boolean, nullable=False, default=True),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)
save_grants = Table(
    "access_save_grants", metadata,
    Column("game_id", String(100), primary_key=True),
    Column("player_id", String(36), primary_key=True),
    Column("save_id", String(36), primary_key=True),
    Column("active", Boolean, nullable=False, default=True),
    ForeignKeyConstraint(["game_id", "player_id"], [players.c.game_id, players.c.player_id]),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)
credentials = Table(
    "access_credentials", metadata,
    Column("credential_id", String(36), primary_key=True),
    Column("game_id", String(100), nullable=False),
    Column("player_id", String(36), nullable=False),
    Column("secret_hash", String(64), nullable=False),
    Column("permissions", String(250), nullable=False),
    Column("created_at", Double, nullable=False),
    Column("expires_at", Double, nullable=False),
    Column("revoked", Boolean, nullable=False, default=False),
    ForeignKeyConstraint(["game_id", "player_id"], [players.c.game_id, players.c.player_id]),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)
quota_usage = Table(
    "access_quotas", metadata,
    Column("game_id", String(100), primary_key=True),
    Column("player_id", String(36), primary_key=True),
    Column("kind", String(20), primary_key=True),
    Column("window_start", BigInteger, primary_key=True),
    Column("used", Integer, nullable=False),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)

_principal = ContextVar("authenticated_principal", default=None)


def _now():
    return time.time()


def _unavailable():
    return ScopeError(503, "AUTH_UNAVAILABLE", "Credential or admission storage is unavailable.")


def _invalid():
    return ScopeError(401, "IDENTITY_REQUIRED", "A valid player credential is required.")


def _engine():
    if not database_enabled():
        raise _unavailable()
    return get_database().engine


def _ids(game_id, player_id):
    return safe_segment(game_id), str(UUID(str(player_id)))


def _player_key(game_id, player_id):
    return (players.c.game_id == game_id) & (players.c.player_id == player_id)


def register_player(game_id, player_id):
    game_id, player_id = _ids(game_id, player_id)
    try:
        with _engine().begin() as connection:
            row = connection.execute(select(players.c.active).where(_player_key(game_id, player_id))).first()
            if row is None:
                connection.execute(insert(players).values(game_id=game_id, player_id=player_id, active=True))
    except IntegrityError:
        # Concurrent registration of the same public identity is harmless.
        return
    except SQLAlchemyError as error:
        raise _unavailable() from error


def set_player_active(game_id, player_id, active):
    game_id, player_id = _ids(game_id, player_id)
    try:
        with _engine().begin() as connection:
            result = connection.execute(update(players).where(_player_key(game_id, player_id)).values(active=bool(active)))
            if result.rowcount != 1:
                raise ValueError("Player is not registered.")
    except SQLAlchemyError as error:
        raise _unavailable() from error


def grant_save(game_id, player_id, save_id, *, active=True):
    game_id, player_id = _ids(game_id, player_id)
    save_id = str(UUID(str(save_id)))
    condition = ((save_grants.c.game_id == game_id) & (save_grants.c.player_id == player_id)
                 & (save_grants.c.save_id == save_id))
    try:
        with _engine().begin() as connection:
            row = connection.execute(select(players.c.active).where(_player_key(game_id, player_id))).first()
            if row is None:
                raise ValueError("Player is not registered.")
            changed = connection.execute(update(save_grants).where(condition).values(active=bool(active)))
            if changed.rowcount == 0:
                connection.execute(insert(save_grants).values(game_id=game_id, player_id=player_id,
                                                              save_id=save_id, active=bool(active)))
    except SQLAlchemyError as error:
        raise _unavailable() from error


def issue_token(game_id, player_id, *, permissions=("npc:use",), ttl_seconds=3600):
    game_id, player_id = _ids(game_id, player_id)
    permissions = frozenset(permissions)
    if not permissions or not permissions <= PERMISSIONS:
        raise ValueError("A nonempty set of known permissions is required.")
    if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
        raise ValueError("A positive finite credential lifetime is required.")
    credential_id = uuid4()
    token = f"aw1.{credential_id.hex}.{secrets.token_urlsafe(32)}"
    created_at = _now()
    try:
        with _engine().begin() as connection:
            active = connection.execute(select(players.c.active).where(_player_key(game_id, player_id))).scalar_one_or_none()
            if active is not True:
                raise ValueError("An active registered player is required.")
            connection.execute(insert(credentials).values(
                credential_id=str(credential_id), game_id=game_id, player_id=player_id,
                secret_hash=hashlib.sha256(token.encode()).hexdigest(), permissions=",".join(sorted(permissions)),
                created_at=created_at, expires_at=created_at + ttl_seconds, revoked=False,
            ))
    except SQLAlchemyError as error:
        raise _unavailable() from error
    return token


def token_id(token):
    if not isinstance(token, str) or len(token) > 128:
        raise _invalid()
    parts = token.split(".")
    if (len(parts) != 3 or parts[0] != "aw1" or not re.fullmatch(r"[0-9a-f]{32}", parts[1])
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", parts[2])):
        raise _invalid()
    return str(UUID(parts[1]))


def revoke_token(credential_id):
    credential_id = str(UUID(str(credential_id)))
    try:
        with _engine().begin() as connection:
            connection.execute(update(credentials).where(credentials.c.credential_id == credential_id).values(revoked=True))
    except SQLAlchemyError as error:
        raise _unavailable() from error


def _read_principal(connection, credential_id, *, token_hash=None):
    from app.scoped.identity import Principal

    row = connection.execute(select(credentials).where(credentials.c.credential_id == str(credential_id))).mappings().first()
    if token_hash is not None:
        expected = row["secret_hash"] if row is not None else "0" * 64
        if not secrets.compare_digest(token_hash, expected):
            raise _invalid()
    if row is None or row["revoked"] or row["expires_at"] <= _now():
        raise _invalid()
    game_id = safe_segment(get_settings().game_id)
    if row["game_id"] != game_id:
        raise _invalid()
    active = connection.execute(select(players.c.active).where(_player_key(row["game_id"], row["player_id"]))).scalar_one_or_none()
    if active is not True:
        raise _invalid()
    permissions = frozenset(row["permissions"].split(","))
    if not permissions or not permissions <= PERMISSIONS:
        raise _unavailable()
    saves = connection.execute(select(save_grants.c.save_id).where(
        (save_grants.c.game_id == row["game_id"]) & (save_grants.c.player_id == row["player_id"])
        & save_grants.c.active.is_(True))).scalars()
    return Principal(UUID(row["player_id"]), frozenset(UUID(value) for value in saves),
                     permissions=permissions, credential_id=UUID(row["credential_id"]), game_id=row["game_id"])


def authenticate_token(token):
    credential_id = token_id(token)
    try:
        with _engine().connect() as connection:
            return _read_principal(connection, credential_id, token_hash=hashlib.sha256(token.encode()).hexdigest())
    except SQLAlchemyError as error:
        raise _unavailable() from error


@contextmanager
def use_principal(principal):
    context_token = _principal.set(principal)
    try:
        yield principal
    finally:
        _principal.reset(context_token)


def current_principal():
    return _principal.get()


def validate_principal(principal, scope=None):
    """Fresh credential/ownership check; no credential or grant cache."""
    if principal is None or principal.credential_id is None:
        if get_settings().scope_identity_backend == "bearer":
            raise _invalid()
        return
    try:
        with _engine().connect() as connection:
            latest = _read_principal(connection, principal.credential_id)
    except SQLAlchemyError as error:
        raise _unavailable() from error
    if latest.player_id != principal.player_id or latest.game_id != principal.game_id:
        raise _invalid()
    if not principal.permissions <= latest.permissions:
        raise ScopeError(403, "PERMISSION_DENIED", "The credential permission was removed.")
    if scope is not None:
        npc = getattr(scope, "npc", scope)
        if npc.player_id != latest.player_id or npc.game_id != latest.game_id or npc.save_id not in latest.save_ids:
            raise ScopeError(403, "SCOPE_FORBIDDEN", "The requested save is not authorized.")


def validate_current_principal(scope=None):
    validate_principal(current_principal(), scope or current_scope())


def _reserve(game_id, player_id, kind, window_seconds, limit):
    game_id, player_id = _ids(game_id, player_id)
    now = _now()
    window_start = int(now // window_seconds) * window_seconds
    condition = ((quota_usage.c.game_id == game_id) & (quota_usage.c.player_id == player_id)
                 & (quota_usage.c.kind == kind) & (quota_usage.c.window_start == window_start))
    for attempt in range(3):
        try:
            with _engine().begin() as connection:
                row = connection.execute(select(quota_usage.c.used).where(condition).with_for_update()).first()
                if row is None:
                    connection.execute(insert(quota_usage).values(game_id=game_id, player_id=player_id,
                                                                  kind=kind, window_start=window_start, used=1))
                    used = 1
                else:
                    changed = connection.execute(update(quota_usage).where(condition & (quota_usage.c.used < limit))
                                                 .values(used=quota_usage.c.used + 1))
                    if changed.rowcount != 1:
                        code = "UPSTREAM_QUOTA_EXCEEDED" if kind == "upstream" else "REQUEST_QUOTA_EXCEEDED"
                        raise ScopeError(429, code, "The configured player admission limit was reached.")
                    used = row[0] + 1
                return {"kind": kind, "used": used, "limit": limit, "window_start": window_start}
        except IntegrityError:
            if attempt == 2:
                raise _unavailable()
        except SQLAlchemyError as error:
            raise _unavailable() from error
    raise _unavailable()


def reserve_request_quota(principal, game_id=None):
    if principal.credential_id is None:
        validate_principal(principal)
        return None
    validate_principal(principal)
    return _reserve(game_id or principal.game_id, principal.player_id, "request", 60,
                    getattr(get_settings(), "scope_request_quota_per_minute", 120))


def reserve_upstream_quota(scope=None):
    principal = current_principal()
    if principal is None or principal.credential_id is None:
        validate_principal(principal)
        return None
    scope = scope or current_scope()
    validate_principal(principal, scope)
    game_id = scope.npc.game_id if scope is not None else principal.game_id
    return _reserve(game_id, principal.player_id, "upstream", 86400,
                    getattr(get_settings(), "scope_upstream_quota_per_day", 200))
