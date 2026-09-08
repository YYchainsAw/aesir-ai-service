"""从运行时配置创建转写后端。"""

from app.config import get_settings
from app.services.transcribers.base import ASRBackend
from app.services.transcribers.mock import MockASRTranscriber


def get_transcriber() -> ASRBackend:
    """按 ``AESIR_ASR_BACKEND`` 创建后端；未识别值回退到 mock 以保可用。

    ``faster_whisper`` 分支返回真实本机转写（模型/设备/量化/语言由 config 决定）。
    """
    if get_settings().asr_backend == "faster_whisper":
        from app.services.transcribers.faster_whisper import FasterWhisperTranscriber

        return FasterWhisperTranscriber()
    return MockASRTranscriber()