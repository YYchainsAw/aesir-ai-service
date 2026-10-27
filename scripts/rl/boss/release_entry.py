"""Standalone Windows release entry; verify before loading trusted model bytes."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import sys


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_bundle(root: Path) -> dict[str, object]:
    """Check the retained inventory. This detects damage, not publisher identity."""
    manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != "aesir-boss-windows-onedir-v1":
        raise ValueError("unsupported release manifest")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("release file inventory is missing")
    for name, expected in files.items():
        if (not isinstance(name, str) or not isinstance(expected, str)
                or len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected)):
            raise ValueError("invalid release file inventory")
        relative = PurePosixPath(name)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                or ":" in name or name == "release-manifest.json"):
            raise ValueError("unsafe path in release inventory")
        target = root.joinpath(*relative.parts)
        if (not target.resolve().is_relative_to(root.resolve())
                or target.is_symlink() or not target.is_file()):
            raise ValueError(f"release file is missing or linked: {name}")
        if file_sha256(target) != expected:
            raise ValueError(f"release file SHA256 mismatch: {name}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*") if path.is_file()
        and path != root / "release-manifest.json"
    }
    if actual != set(files):
        raise ValueError("release inventory contains unlisted or missing files")
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aesir frozen Boss local CPU service")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="verify bytes without loading model")
    mode.add_argument("--self-test", action="store_true", help="verify and run offline CPU mask checks")
    parser.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not getattr(sys, "frozen", False):
            raise ValueError("this entry is for the built Windows release; use scripts.rl.boss.serve for source")
        if os.getenv("AESIR_BOSS_POLICY_MODEL"):
            raise ValueError("the frozen release does not accept AESIR_BOSS_POLICY_MODEL overrides")
        root = Path(sys.executable).resolve().parent
        manifest = verify_bundle(root)
        from rl.boss.release import default_model_path, validate_frozen_artifact

        model_path = default_model_path()
        provenance = validate_frozen_artifact(model_path)
        if manifest.get("model") != provenance:
            raise ValueError("release manifest model provenance mismatch")
        if args.verify:
            print(json.dumps({"verified": True, "model_loaded": False, **provenance}))
            return 0

        from rl.boss.inference import BossPolicyRuntime

        runtime = BossPolicyRuntime(model_path)
        runtime.load()
        if args.self_test:
            from rl.boss.contract import ACTION_COUNT, OBSERVATION_DIM

            observation = [0.5] * (OBSERVATION_DIM - ACTION_COUNT) + [0.0] * ACTION_COUNT
            locked = runtime.decide(observation)
            if locked.actionable or locked.action is not None:
                raise ValueError("locked-state self-test failed")
            actions = []
            for action in range(ACTION_COUNT):
                observation[-ACTION_COUNT:] = [float(index == action) for index in range(ACTION_COUNT)]
                decision = runtime.decide(observation)
                repeat = runtime.decide(observation)
                if (not decision.actionable or decision.action is None
                        or int(decision.action) != action or repeat.action != decision.action):
                    raise ValueError(f"CPU action-mask self-test failed: {action}")
                actions.append(int(decision.action))
            print(json.dumps({"self_test": "passed", "device": "cpu", "actions": actions,
                              "locked_state": True, **provenance}))
            return 0

        import uvicorn
        from rl.boss.inference_app import create_app

        uvicorn.run(create_app(runtime), host=args.host, port=args.port,
                    reload=False, workers=1, loop="asyncio", http="h11", ws="none")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
