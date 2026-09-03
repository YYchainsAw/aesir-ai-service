"""Mock 转写后端：返回配置的固定文本，用于在无模型环境下打通语音全链路。

真实音频不解析；``AESIR_ASR_MOCK_TEXT`` 决定「转出」的指令文本，留空则视为
没转出命令（下游走 ``recognized:false``）。
"""

from app.config import get_asr_mock_text
from app.services.transcribers.base import ASRBackend


class MockASRTranscriber(ASRBackend):
    def transcribe(self, audio: bytes) -> str:
        return get_asr_mock_text()