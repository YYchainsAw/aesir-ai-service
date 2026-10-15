"""运行时版本标识（T21 / #34）。

启动时跑一次 ``git rev-parse --short HEAD`` 缓存结果，供 /health 与
各协议响应装配——UE 侧不读代码也能确认当前跑的是哪个 commit。
非 git 环境（打包分发、测试临时目录）返回 ``unknown``，不阻塞启动。
"""

from __future__ import annotations

import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def get_service_commit() -> str:
    """返回 short git SHA；失败时返回 ``unknown``。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"
