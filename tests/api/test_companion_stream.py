"""/v1/companion/chat/stream（SSE）契约测试：帧形状、mock 后端、LLM 后端、错误路径。"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.llm.client import LLMClientError

client = TestClient(app)


_FULL_LLM_REPLY = (
    '{"reply_text": "好呀，那就走吧。", '
    '"emotion_id": "emotion.bright", '
    '"gesture_id": "gesture.cheerful_idle", '
    '"facial_expression_id": "face.bright_smile", '
    '"interruptible": true, '
    '"topics": ["高塔"], "facts": ["玩家怕高"]}'
)


class _StubStreamingClient:
    """按预定 chunk 列表产出流式增量；可在任意位置抛 LLMClientError。"""

    def __init__(self, chunks, *, fail_after: int | None = None) -> None:
        self._chunks = chunks
        self._fail_after = fail_after  # 抛错前已 yield 的 chunk 数

    def generate_json(self, *, system_prompt, user_prompt, temperature=0.2):
        raise AssertionError("stream path must not call generate_json")

    def stream_completion(self, *, system_prompt, user_prompt, temperature=0.2):
        yielded = 0
        for chunk in self._chunks:
            yield chunk
            yielded += 1
            if self._fail_after is not None and yielded >= self._fail_after:
                raise LLMClientError("stream interrupted mid-flight")


def _parse_frames(text: str) -> list[tuple[str, dict]]:
    """把原始 SSE 文本解析成 (event, data) 列表。"""
    frames = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        kind = ""
        data = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                kind = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        frames.append((kind, data))
    return frames


def test_stream_mock_backend_emits_delta_then_meta() -> None:
    response = client.post(
        "/v1/companion/chat/stream",
        json={"text": "我们出发吧。", "session_id": "stream-1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = _parse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert kinds[-1] == "meta"
    assert "delta" in kinds
    assert kinds == ["delta", "meta"]  # mock 后端：单 delta（全文）+ meta

    delta = next(data for kind, data in frames if kind == "delta")
    meta = next(data for kind, data in frames if kind == "meta")
    assert delta["text"] == meta["reply_text"]
    assert meta["source"] == "mock"
    assert meta["session_id"] == "stream-1"
    assert set(
        (
            "protocol_version",
            "companion_id",
            "session_id",
            "reply_text",
            "emotion_id",
            "gesture_id",
            "facial_expression_id",
            "interruptible",
            "source",
            "relationship_stage",
        )
    ) <= set(meta)


def test_stream_rejects_combat_state() -> None:
    response = client.post(
        "/v1/companion/chat/stream",
        json={"text": "进攻", "game_state": "combat"},
    )
    assert response.status_code == 422


def test_stream_unknown_companion_returns_404_before_stream() -> None:
    response = client.post(
        "/v1/companion/chat/stream",
        json={"text": "你好", "companion_id": "companion.nobody"},
    )
    assert response.status_code == 404


# --- LLM 后端（无付费桩）---------------------------------------------
#
# 回归 #102：stream_dialogue_reply 曾把 game_id 传给 _stream_llm_reply，
# 但后者签名不接收该参数，切到 llm 后端时立刻 TypeError。这些测试
# 直接走真实服务入口（stream_dialogue_reply → SSE 端点），不绕过认证。


@pytest.fixture
def _llm_backend(monkeypatch):
    """切到 llm 后端，并把 create_llm_client 替换成可控桩。"""
    from app.services.companion import llm_dialogue_service as llm_module

    # get_settings() 每次新建实例读环境变量，必须 monkeypatch env。
    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "llm")

    def _install(chunks, *, fail_after=None):
        monkeypatch.setattr(
            llm_module, "create_llm_client",
            lambda: _StubStreamingClient(chunks, fail_after=fail_after),
        )

    return _install


def test_stream_llm_backend_emits_delta_then_meta(_llm_backend) -> None:
    """FIX #102：LLM 后端正常流应输出 delta（拆块）+ meta（source=llm）。"""
    chunks = [_FULL_LLM_REPLY[i:i + 7] for i in range(0, len(_FULL_LLM_REPLY), 7)]
    _llm_backend(chunks)

    response = client.post(
        "/v1/companion/chat/stream",
        json={"text": "我们出发吧。", "session_id": "stream-llm-1"},
    )
    assert response.status_code == 200
    frames = _parse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert kinds[-1] == "meta"
    assert kinds[0] == "delta"
    assert "delta" in kinds

    joined_delta = "".join(
        data["text"] for kind, data in frames if kind == "delta"
    )
    meta = next(data for kind, data in frames if kind == "meta")
    assert joined_delta == meta["reply_text"]
    assert meta["source"] == "llm"
    assert meta["reply_text"] == "好呀，那就走吧。"


def test_stream_llm_pre_failure_falls_back_to_mock(_llm_backend) -> None:
    """LLM 在发出任何 delta 前失败 → 静默回退 mock（source=fallback）。"""
    _llm_backend([], fail_after=0)  # stream_completion 第一次迭代就抛

    response = client.post(
        "/v1/companion/chat/stream",
        json={"text": "你好", "session_id": "stream-llm-fb"},
    )
    assert response.status_code == 200
    frames = _parse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert kinds == ["delta", "meta"]
    meta = next(data for kind, data in frames if kind == "meta")
    assert meta["source"] == "fallback"


def test_stream_llm_mid_failure_emits_error_frame(_llm_backend) -> None:
    """已发出 delta 后中断 → yield error 事件并停止（不再发 meta）。"""
    # 先吐出一个不完整 chunk（会被拼成半截 JSON），第二次迭代抛错。
    _llm_backend(["{\"reply_text\": \"好"], fail_after=1)

    response = client.post(
        "/v1/companion/chat/stream",
        json={"text": "你好", "session_id": "stream-llm-err"},
    )
    assert response.status_code == 200
    frames = _parse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert "error" in kinds
    assert "meta" not in kinds  # 中途失败不发权威 meta
