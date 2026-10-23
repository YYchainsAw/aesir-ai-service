"""Run the standalone frozen Boss policy service."""

import argparse
from ipaddress import ip_address
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the frozen Boss policy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--model", type=Path, default=None)
    args = parser.parse_args()
    try:
        loopback = ip_address(args.host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        parser.error("Boss inference only accepts a literal loopback address")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    return args


def main() -> None:
    args = parse_args()
    if args.model is not None:
        if not args.model.is_file():
            raise SystemExit(f"model does not exist: {args.model}")
        os.environ["AESIR_BOSS_POLICY_MODEL"] = str(args.model.resolve())

    import uvicorn
    from rl.boss.inference import BossPolicyRuntime
    from rl.boss.inference_app import create_app

    runtime = BossPolicyRuntime(args.model)
    uvicorn.run(
        create_app(runtime),
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
