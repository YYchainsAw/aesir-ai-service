"""从运行时配置创建转写后端。"""

from app.config import get_asr_backend
from app.services.transcribers.base import ASRBackend
from app.services.transcribers.mock import MockASRTranscriber


def get_transcriber() -> ASRBackend:
    """按 ``AESIR_ASR_BACKEND`` 创建后端；未识别值回退到 mock 以保可用。

    TODO(阶段3)：接入 faster-whisper 时在此按 ``"faster_whisper"`` 分支构造，
    返回 ``services.transcribers.faster_whisper.FasterWhisperTranscriber``。
    """
    if get_asr_backend() == "faster_whisper":
        from app.services.transcribers.faster_whisper import FasterWhisperTranscriber

        return FasterWhisperTranscriber()
    return MockASRTranscriber()