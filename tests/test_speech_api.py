"""独立转写端点 /v1/speech/transcribe 的测试。

与 test_voice.py 同样注入转写桩，不加载真实模型；真机冒烟见
tests/test_transcriber_faster_whisper.py（AESIR_ASR_SMOKE=1 门控）。
"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app

# 与 test_voice.py 相同：patch 路由模块内绑定的 get_transcriber 引用。
PATCH_TARGET = "app.api.v1.speech.get_transcriber"

client = TestClient(app)

RID = "1fad2e69-4a2d-4308-ad4f-2f8abb338b89"


class StubTranscriber:
    """返回预设文本的转写桩。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, audio: bytes) -> str:
        return self.text


def _audio_file() -> dict:
    return {"audio": ("cmd.wav", b"RIFFfakeaudio", "audio/wav")}


def test_transcribe_returns_text_and_echoes_request_id(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("艾琳，撤退并优先保命"))
    response = client.post(
        "/v1/speech/transcribe",
        files=_audio_file(),
        data={"request_id": RID},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["request_id"] == RID
    assert body["text"] == "艾琳，撤退并优先保命"
    assert body["language"] == "zh"


def test_transcribe_generates_request_id_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("艾琳，撤退"))
    response = client.post("/v1/speech/transcribe", files=_audio_file())

    body = response.json()
    assert response.status_code == 200
    UUID(body["request_id"])  # 服务端生成了合法 UUID


def test_transcribe_empty_text_is_still_200(monkeypatch) -> None:
    """空音频/未识别：HTTP 200 + text 空串，由 UE 决定后续行为。"""
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber(""))
    response = client.post("/v1/speech/transcribe", files=_audio_file())

    body = response.json()
    assert response.status_code == 200
    assert body["text"] == ""


def test_transcribe_invalid_request_id_returns_422(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("艾琳，撤退"))
    response = client.post(
        "/v1/speech/transcribe",
        files=_audio_file(),
        data={"request_id": "not-a-uuid"},
    )

    assert response.status_code == 422


def test_transcribe_error_returns_502(monkeypatch) -> None:
    from app.services.transcribers.base import TranscriptionError

    class FailingTranscriber:
        def transcribe(self, audio: bytes) -> str:
            raise TranscriptionError("ASR model unavailable")

    monkeypatch.setattr(PATCH_TARGET, lambda: FailingTranscriber())
    response = client.post("/v1/speech/transcribe", files=_audio_file())

    assert response.status_code == 502
    assert "ASR model unavailable" in response.text
