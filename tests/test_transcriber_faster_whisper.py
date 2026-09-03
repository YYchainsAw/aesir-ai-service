"""faster-whisper 后端测试。

默认环境（未装 faster-whisper / 未设 AESIR_ASR_SMOKE=1）下只跑空音频那条纯逻辑
用例，不加载模型、不依赖 ML 包，不拖慢既有测试集。需要真机冒烟时才启用：

    # PowerShell:  $env:AESIR_ASR_SMOKE = "1"
    python -m pytest tests/test_transcriber_faster_whisper.py -m asr_smoke
"""

import io
import os
import wave

import pytest

from app.services.transcribers.faster_whisper import FasterWhisperTranscriber


def test_transcribe_empty_audio_returns_empty() -> None:
    """空音频直接返回空串，不触发模型加载（纯逻辑，无 ML 依赖）。"""
    assert FasterWhisperTranscriber().transcribe(b"") == ""


# 以下用例需要已安装 faster-whisper，缺依赖时整体跳过（不影响既有测试）
fw = pytest.importorskip("faster_whisper", reason="未安装 faster-whisper")

from app.services.transcribers import factory  # noqa: E402


def test_factory_selects_faster_whisper(monkeypatch) -> None:
    """按 env 选到真实后端（构造不加载模型，只需依赖在）。"""
    monkeypatch.setenv("AESIR_ASR_BACKEND", "faster_whisper")
    transcriber = factory.get_transcriber()
    assert isinstance(transcriber, FasterWhisperTranscriber)


# ---- 真机冒烟：需 AESIR_ASR_SMOKE=1 且模型可加载（可能触发下载，国内配 HF 镜像） ----
asr_smoke = pytest.mark.skipif(
    os.environ.get("AESIR_ASR_SMOKE") != "1",
    reason="真机冒烟需 AESIR_ASR_SMOKE=1",
)


def _silent_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    """生成一段全零静音 16k / 单声道 / 16bit WAV，供 VAD 过滤验证。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(rate * seconds))
    return buf.getvalue()


@asr_smoke
def test_transcribes_silent_wav_returns_empty() -> None:
    """静音经 VAD 过滤后应为空文本（验证全链路无异常）。"""
    text = FasterWhisperTranscriber().transcribe(_silent_wav())
    assert text.strip() == ""


@asr_smoke
def test_transcribe_raises_on_invalid_audio() -> None:
    """非法音频（非 WAV）抛 TranscriptionError → 上层 502。"""
    from app.services.transcribers.base import TranscriptionError

    with pytest.raises(TranscriptionError):
        FasterWhisperTranscriber().transcribe(b"this is not audio")