"""语音陪伴对话端点 /v1/companion/chat/voice 的全链路测试。

音频 → ASR 转写 → 既有陪伴对话链路（记忆/关系/信号埋点全部生效）。
转写后端注入桩，不加载真实模型（与 test_voice.py 同款推进方式）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.transcribers.base import TranscriptionError

# 路由模块级绑定的引用，须 patch 路由模块里的名字（与 test_voice.py 同理）。
PATCH_TARGET = "app.api.v1.companion.get_transcriber"

client = TestClient(app)


class StubTranscriber:
    """返回预设文本的转写桩。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, audio: bytes) -> str:
        return self.text


class ExplodingTranscriber:
    """转写失败桩（模拟模型/音频故障）。"""

    def transcribe(self, audio: bytes) -> str:
        raise TranscriptionError("asr backend failed")


def _audio_file() -> dict:
    return {"audio": ("say.wav", b"RIFFfakeaudio", "audio/wav")}


def test_voice_chat_full_chain(monkeypatch, tmp_path) -> None:
    """转写文本进入对话链路：回复、记忆印象、信号埋点全部生效。"""
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("钓鱼吗"))
    response = client.post(
        "/v1/companion/chat/voice",
        files=_audio_file(),
        data={"companion_id": "companion.alice", "game_state": "conversation", "session_id": "v1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["transcribed_text"] == "钓鱼吗"
    assert body["reply_text"]
    assert body["source"] in ("mock", "llm", "fallback")

    # 记忆链路生效：转写文本的主题入印象。
    from app.services.memory.store import get_memory_store

    assert "钓鱼" in [i.topic for i in get_memory_store("companion.alice").snapshot().impressions]
    # 信号埋点生效：本轮落了 JSONL 记录（conftest 已把目录指到 tmp_path）。
    records = [
        json.loads(line)
        for line in (tmp_path / "signals" / "companion.alice.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(r["player_text"] == "钓鱼吗" for r in records)


def test_empty_transcription_rejected(monkeypatch) -> None:
    """没转出语音内容：422 明确拒绝，不拿空文本进对话。"""
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber(""))
    response = client.post("/v1/companion/chat/voice", files=_audio_file())
    assert response.status_code == 422
    assert "未识别出语音内容" in response.json()["detail"]


def test_transcription_failure_returns_502(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, ExplodingTranscriber)
    response = client.post("/v1/companion/chat/voice", files=_audio_file())
    assert response.status_code == 502


def test_unknown_companion_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("你好"))
    response = client.post(
        "/v1/companion/chat/voice",
        files=_audio_file(),
        data={"companion_id": "companion.unknown"},
    )
    assert response.status_code == 404


def test_invalid_game_state_rejected(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("你好"))
    response = client.post(
        "/v1/companion/chat/voice",
        files=_audio_file(),
        data={"game_state": "combat"},
    )
    assert response.status_code == 422


def test_invalid_world_context_json_rejected(monkeypatch) -> None:
    monkeypatch.setattr(PATCH_TARGET, lambda: StubTranscriber("你好"))
    response = client.post(
        "/v1/companion/chat/voice",
        files=_audio_file(),
        data={"world_context_json": "{not json"},
    )
    assert response.status_code == 422
