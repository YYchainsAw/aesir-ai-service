"""基于 faster-whisper 的本地语音转写后端。

把 UE 上传的 WAV（默认 16kHz / 单声道 / 16bit）转成文本，再送入解析层。
faster-whisper 用 ctranslate2 加速 Whisper：模型默认 ``small``（8GB 显存足够、
中文够用、一句话约 0.5s，远低于 UE 3s 预算），首次使用按需下载。

模型实例做进程级懒加载缓存（``_load_model``），避免每次请求重新读权重。
faster-whisper 为延迟导入，核心服务（mock 后端）不依赖 ML 栈。
"""

import io
import logging
from functools import lru_cache

from app.config import (
    get_asr_compute_type,
    get_asr_device,
    get_asr_language,
    get_asr_model,
)
from app.services.transcribers.base import ASRBackend, TranscriptionError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_model():
    """省懒加载 faster-whisper 模型并缓存（进程级单例）。

    返回 ``faster_whisper.WhisperModel``。加载失败抛出的异常由
    调用方包装成 ``TranscriptionError``（对上层呈现 502）。
    """
    from faster_whisper import WhisperModel  # 延迟导入：无需 ML 栈也能跑服务

    return WhisperModel(
        get_asr_model(),
        device=get_asr_device(),
        compute_type=get_asr_compute_type(),
    )


class FasterWhisperTranscriber(ASRBackend):
    """把音频 bytes 转写为文本。空音频直接返回空串，不触发模型加载。"""

    def __init__(self) -> None:
        self.language = get_asr_language()

    def transcribe(self, audio: bytes) -> str:
        if not audio:
            return ""

        try:
            segments, _info = _load_model().transcribe(
                io.BytesIO(audio),
                language=self.language,
                beam_size=1,  # 贪心解码：短指令下比 beam=5 快得多，准确率损失可忽略
                vad_filter=True,  # 过滤静音/尾音，降低误识别
            )
            return "".join(seg.text for seg in segments).strip()
        except TranscriptionError:
            raise
        except Exception as exc:
            # 透传给上层：模型下载失败、推理异常、解码失败等都归为转写错误 → 502
            logger.exception("faster-whisper 转写失败")
            raise TranscriptionError(f"ASR transcription failed: {exc}") from exc