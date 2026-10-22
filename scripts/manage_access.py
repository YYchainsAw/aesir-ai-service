"""Offline access administration; token secrets only go to a new 0600 file.

Run with the explicitly selected application database configuration. No access
issuance API is exposed and no provider key is needed by this command.
"""
from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path
import sys
from uuid import UUID, uuid4

from app.config import get_settings
from app.persistence.auth import (grant_save, issue_token, register_player,
                                  revoke_token, set_player_active, token_id)
from app.scoped.errors import ScopeError


def _write_token(path, game_id, player_id, permissions, ttl_seconds):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("Credential output requires an absolute private path.")
    resolved = path.resolve()
    checkout = Path(__file__).resolve().parents[1]
    if resolved.is_relative_to(checkout):
        raise ValueError("Credential output must be outside the source checkout.")
    if os.name == "posix":
        if resolved.is_relative_to(Path("/www/wwwroot")):
            raise ValueError("Credential output must be outside the static web root.")
        if stat.S_IMODE(resolved.parent.stat().st_mode) & 0o077:
            raise ValueError("Credential output requires a private parent directory.")
    # O_EXCL rejects both existing files and symlinks without overwriting them.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    token = None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            token = issue_token(game_id, player_id, permissions=permissions, ttl_seconds=ttl_seconds)
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            directory = os.open(path.resolve().parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except Exception:
        if token is not None:
            try:
                revoke_token(token_id(token))
            except Exception:
                # Keep the original failure generic. Administrative reconciliation
                # can inspect credential IDs; never print the bearer secret.
                pass
        path.unlink(missing_ok=True)
        raise
    return token_id(token)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Administer application access without exposing token secrets")
    parser.add_argument("--game-id", default=get_settings().game_id)
    commands = parser.add_subparsers(dest="command", required=True)
    player = commands.add_parser("player-create")
    player.add_argument("--player-id", type=UUID, default=None)
    state = commands.add_parser("player-state")
    state.add_argument("--player-id", type=UUID, required=True)
    state.add_argument("--active", choices=["true", "false"], required=True)
    for name in ("save-grant", "save-revoke"):
        command = commands.add_parser(name)
        command.add_argument("--player-id", type=UUID, required=True)
        command.add_argument("--save-id", type=UUID, required=True)
    token = commands.add_parser("token-issue")
    token.add_argument("--player-id", type=UUID, required=True)
    token.add_argument("--permission", action="append", default=None,
                       choices=["npc:use", "console:read", "memory:reset", "docs:read"])
    token.add_argument("--ttl-seconds", type=float, default=3600)
    token.add_argument("--output", type=Path, required=True,
                       help="New file in an existing private directory; never overwritten")
    revoke = commands.add_parser("token-revoke")
    revoke.add_argument("--credential-id", type=UUID, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "player-create":
            player_id = args.player_id or uuid4()
            register_player(args.game_id, player_id)
            print(f"player_id={player_id}")
        elif args.command == "player-state":
            set_player_active(args.game_id, args.player_id, args.active == "true")
            print("Player access state updated.")
        elif args.command in {"save-grant", "save-revoke"}:
            grant_save(args.game_id, args.player_id, args.save_id, active=args.command == "save-grant")
            print("Save authorization updated.")
        elif args.command == "token-revoke":
            revoke_token(args.credential_id)
            print("Credential revoked.")
        else:
            credential_id = _write_token(args.output, args.game_id, args.player_id,
                                         args.permission or ["npc:use"], args.ttl_seconds)
            print(f"credential_id={credential_id}; token saved to the requested private file.")
        return 0
    except (ScopeError, ValueError, OSError):
        # Do not print SQL driver errors, DSNs, provider keys, token text or paths.
        print("Access administration failed; verify private configuration and arguments.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
