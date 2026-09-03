"""语音转写抽象（可插拔后端）。

和命令解析一样采用「后端可替换」设计：mock 桩与将来的 faster-whisper 等真实
ASR 并存，均只负责「音频 → 中文文本」，文本再接既有 ``parse_command`` 解析层。
UE 协议与解析逻辑不归本层，换后端不改接口。
"""

from abc import ABC, abstractmethod


class TranscriptionError(RuntimeError):
    """转写失败（模型加载失败、音频解码失败等）。路由层据此回 5xx。"""


class ASRBackend(ABC):
    """把一段 WAV（16kHz / 单声道 / 16bit）音频转写为中文字符串。"""

    @abstractmethod
    def transcribe(self, audio: bytes) -> str:
        """输入原始音频字节，返回转写文本；未能识别返回空串。"""