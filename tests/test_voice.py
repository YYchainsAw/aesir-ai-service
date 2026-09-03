"""语音端点 /v1/voice/command 的全链路测试。

转写后端是可插拔的：这里注入桩（StubTranscriber）复用例均不加载真实模型，
符合项目「mock 打通全链路、后再接真实 ASR」的推进方式。
"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.tactical_order import DEFAULT_CONTEXT

# 路由在模块级 `from ...factory import get_transcriber` 已绑定该名字，
# 因此测试须 patch 路由模块里的引用，而不是 factory 模块属性。
PATCH_TARGET = "app.api.v1.voice.get_transcriber"

client = TestClient(app)


@pytest.fixture(autouse=True)
def force_rule_tactical_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """语音链路仍是「解析层」的一部分，接口测试不得碰开发者本机真实 LLM。"""
    monkeypatch.setenv("AESIR_PARSER_BACKEND", "rule")


class StubTranscriber:
    """返回预设文本的转写桩。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, audio: bytes) -> str:
        return self.text


RID = "1fad2e69-4a2d-4308-ad4f-2f8abb338b89"


def _command_file() -> dict:
    return {"file": ("cmd.wav", b"RIFFfakeaudio", "audio/wav")}


def test_transcribe_then_parse_produces_order(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("艾琳，撤退并优先保命"))
    response = client.post(
        "/v1/voice/command",
        files=_command_file(),
        data={"request_id": RID, "context_json": DEFAULT_CONTEXT.model_dump_json()},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["recognized"] is True
    assert body["request_id"] == RID
    assert body["order"]["intent"] == "retreat"
    assert body["order"]["then"] == {"type": "retreat"}


def test_mock_backend_returns_configured_text(monkeypatch) -> None:
    # 不注入桩，走真实 mock 后端；由 AESIR_ASR_MOCK_TEXT 决定转出文本
    monkeypatch.setenv("AESIR_ASR_BACKEND", "mock")
    monkeypatch.setenv("AESIR_ASR_MOCK_TEXT", "艾琳，优先普通攻击")
    response = client.post("/v1/voice/command", files=_command_file())

    body = response.json()
    assert body["recognized"] is True
    assert body["order"]["intent"] == "prioritize_attack"
    assert body["request_id"]
    UUID(body["request_id"])


def test_empty_transcript_is_recognized_false(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber(""))
    response = client.post("/v1/voice/command", files=_command_file())

    body = response.json()
    assert response.status_code == 200
    assert body["recognized"] is False
    assert body["order"] is None
    assert body["message"]  # 未识别文案


def test_invalid_request_id_returns_422(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("艾琳，撤退"))
    response = client.post(
        "/v1/voice/command",
        files=_command_file(),
        data={"request_id": "not-a-uuid"},
    )

    assert response.status_code == 422


def test_invalid_context_json_returns_422(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("艾琳，撤退"))
    response = client.post(
        "/v1/voice/command",
        files=_command_file(),
        data={"context_json": "{not valid json"},
    )

    assert response.status_code == 422


def test_transcriber_error_returns_502(monkeypatch) -> None:
    from app.services.transcribers.base import TranscriptionError

    class FailingTranscriber:
        def transcribe(self, audio: bytes) -> str:
            raise TranscriptionError("ASR model unavailable")

    monkeypatch.setattr(PATCH_TARGET, lambda: FailingTranscriber())
    response = client.post("/v1/voice/command", files=_command_file())

    assert response.status_code == 502
    assert "ASR model unavailable" in response.text