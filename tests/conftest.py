"""全量测试共享 fixture。

目录镜像 app/ 结构：``tests/api``（端点）、``tests/services``（服务层）、
``tests/schemas``（契约）、``tests/rl``（RL 包）。文件名保持全局唯一，
子目录不加 ``__init__.py``。
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 兜底 sys.path：未 editable install 时（如 CI 只装了 pytest）也能定位 app/rl 包。
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """接口/服务测试不受开发者本机 .env 里的 LLM 后端配置干扰。

    需要真实 LLM 后端的测试在自己的测试内 monkeypatch 覆盖即可
    （monkeypatch 在 autouse fixture 之后执行，总是生效）。
    """
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "mock")
    monkeypatch.delenv("AESIR_PARSER_BACKEND", raising=False)


@pytest.fixture(scope="session")
def client() -> TestClient:
    """共享的 TestClient（模块级自建 client 的旧测试不受影响）。"""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_profile_cache():
    """人设 mtime 缓存在每个测试后清空，避免跨测试串味。"""
    from app.services.companion.profile_repository import _profile_cache

    _profile_cache.clear()
    yield
    _profile_cache.clear()


@pytest.fixture(autouse=True)
def _isolate_memory_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """记忆体系测试隔离：运行期记忆一律落在临时目录，不污染 data/memory/。

    （SDD T003：data/memory/ 属运行期产物；测试也不得写入仓库目录。）
    """
    monkeypatch.setenv("AESIR_MEMORY_ROOT", str(tmp_path / "memory"))
    from app.services.memory import store as memory_store_module

    memory_store_module.reset_memory_stores()
    yield
    memory_store_module.reset_memory_stores()
