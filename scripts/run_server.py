"""按 ``app.config.Settings`` 启动 uvicorn 服务。

用法：
    .venv/Scripts/python -m scripts.run_server [--reload]

优先读取环境变量 / .env 中的：
    AESIR_SERVICE_HOST（默认 127.0.0.1）
    AESIR_SERVICE_PORT（默认 8000）

命令行 ``--host`` / ``--port`` 可覆盖配置；未提供时走配置默认值，
避免 ``start.bat``、文档与 UE 各子系统口径不一致（FIX-01）。
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from app.config import get_settings


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Aesir AI Service launcher")
    parser.add_argument("--host", default=settings.service_host, help="监听地址")
    parser.add_argument("--port", type=int, default=settings.service_port, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式自动重载")
    args = parser.parse_args()

    print(f"[INFO] 启动 Aesir AI Service at http://{args.host}:{args.port}")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
