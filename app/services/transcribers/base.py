"""语音转写抽象（可插拔后端）。

和命令解析一样采用「后端可替换」设计：mock 桩与将来的 faster-whisper 等真实
ASR 并存，均只负责「音频 → 中文文本」，文本再接既有 ``parse_command`` 解析层。
UE 协议与解析逻辑不归本层，换后端不改接口。
"""

from abc import ABC, abstractmethod
import io
import wave


class TranscriptionError(RuntimeError):
    """转写失败（模型加载失败、音频解码失败等）。路由层据此回 5xx。"""


class AudioValidationError(TranscriptionError):
    """音频不满足当前上传约束；不向外部供应商发送。"""

    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def validate_pcm_wav(audio: bytes, *, max_bytes: int, max_seconds: float) -> None:
    """Reject oversized, unsupported or truncated recordings before inference."""
    if len(audio) > max_bytes:
        raise AudioValidationError("Audio exceeds the configured byte limit.",
                                   code="AUDIO_TOO_LARGE", status_code=413)
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if wav.getcomptype() != "NONE" or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError("PCM WAV must be mono, 16-bit")
            if wav.getframerate() != 16000 or wav.getnframes() == 0:
                raise ValueError("PCM WAV must contain 16 kHz samples")
            if wav.getnframes() / wav.getframerate() > max_seconds:
                raise AudioValidationError("Audio exceeds the configured duration limit.", code="AUDIO_TOO_LONG")
            expected = wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
            if len(wav.readframes(wav.getnframes())) != expected:
                raise ValueError("Truncated PCM WAV")
    except AudioValidationError:
        raise
    except (wave.Error, EOFError, ValueError, OSError):
        raise AudioValidationError("Supply a complete 16 kHz, mono, 16-bit PCM WAV recording.",
                                   code="AUDIO_INVALID_FORMAT") from None


class ASRBackend(ABC):
    """把一段 WAV（16kHz / 单声道 / 16bit）音频转写为中文字符串。"""

    @abstractmethod
    def transcribe(self, audio: bytes) -> str:
        """输入原始音频字节，返回转写文本；未能识别返回空串。"""
