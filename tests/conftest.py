"""全量测试共享 fixture。

目录镜像 app/ 结构：``tests/api``（端点）、``tests/services``（服务层）、
``tests/schemas``（契约）、``tests/rl``（RL 包）。文件名保持全局唯一，
子目录不加 ``__init__.py``。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 兜底 sys.path：未 editable install 时（如 CI 只装了 pytest）也能定位 app/rl 包。
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Windows 下把临时基座指向短目录。pytest 默认基座 %TEMP%/pytest-of-<user>/...
# 本身已 ~90 字符，叠加 v0.4 作用域信号目录（game/player/save/npc/run 三层 UUID）
# 会突破 MAX_PATH(260)，使 open() 报 FileNotFoundError[Errno 2]——这不是时序竞争，
# 是路径长度。Linux/macOS 无此限制，保持默认。
if sys.platform == "win32":
    os.makedirs(r"C:\aesir_pytmp", exist_ok=True)
    tempfile.tempdir = r"C:\aesir_pytmp"

from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """接口/服务测试不受开发者本机 .env 里的 LLM 后端配置干扰。

    需要真实 LLM 后端的测试在自己的测试内 monkeypatch 覆盖即可
    （monkeypatch 在 autouse fixture 之后执行，总是生效）。
    """
    # 旧协议回归显式进入开发兼容模式；scoped HTTP 测试自行关闭。
    monkeypatch.setenv("AESIR_SCOPE_LEGACY_ENABLED", "true")
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "mock")
    monkeypatch.delenv("AESIR_PARSER_BACKEND", raising=False)
    # 阶段 0e：生产默认 Redis 后端；测试环境强制内存后端（Redis 语义已被
    # test_redis_scheduling / test_shadow_scheduling / test_redis_chaos 直接覆盖）。
    monkeypatch.setenv("AESIR_COORDINATION_BACKEND", "memory")


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


@pytest.fixture(autouse=True)
def _isolate_relationship_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """关系体系测试隔离：运行期关系状态一律落在临时目录，不污染 data/relationship/。

    （与记忆同款约定；US5 事件联动会写关系数值，因此 API 测试也必须隔离。）
    """
    monkeypatch.setenv("AESIR_RELATIONSHIP_ROOT", str(tmp_path / "relationship"))
    from app.services.relationship import state as relationship_state_module

    relationship_state_module.reset_relationship_stores()
    yield
    relationship_state_module.reset_relationship_stores()


@pytest.fixture(autouse=True)
def _isolate_dialogue_signals_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """对话信号埋点隔离：测试的 JSONL 一律落临时目录，不污染真实信号数据。

    信号数据是 RL 前置资产，混入测试 mock 回复会污染日后训练/分析。
    """
    monkeypatch.setenv("AESIR_DIALOGUE_SIGNALS_DIR", str(tmp_path / "signals"))
    monkeypatch.setenv("AESIR_REQUEST_TRACES_DIR", str(tmp_path / "request_traces"))
    yield
