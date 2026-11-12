"""Run the standalone frozen Boss policy service."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the frozen Boss policy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None,
                        help="training manifest (default: <model>.training.manifest.json)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    import uvicorn
    from rl.boss.inference import BossPolicyRuntime
    from rl.boss.inference_app import create_app

    uvicorn.run(
        create_app(BossPolicyRuntime(args.model, manifest_path=args.manifest)),
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
