"""Aesir AI 服务的运行时配置。

若项目根目录存在 ``.env``，会在 import 时自动加载（依赖 ``python-dotenv``）。
所有配置项都有安全默认值，因此即使没有 ``.env`` 也能直接运行。
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float


def get_parser_backend() -> str:
    """返回当前生效的命令解析后端。

    每次调用时读取（而非在 import 时读取），方便在运行时切换，也便于测试时
    覆盖环境变量。取值：``rule``（默认）或 ``llm``。
    """
    return os.environ.get("AESIR_PARSER_BACKEND", "rule")


def get_companion_backend() -> str:
    """返回陪伴对话后端：mock（默认）或 llm。"""
    return os.environ.get("AESIR_COMPANION_BACKEND", "mock")


def get_asr_backend() -> str:
    """返回当前生效的语音转写后端：mock（默认，固定文本）或 faster_whisper（待接入）。"""
    return os.environ.get("AESIR_ASR_BACKEND", "mock")


def get_asr_mock_text() -> str:
    """mock 转写后端返回的固定文本；留空则视为没转出命令（recognized:false）。"""
    return os.environ.get("AESIR_ASR_MOCK_TEXT", "")


def get_llm_settings() -> LLMSettings:
    """读取两个业务链路共用的 LLM Provider 配置。"""
    return LLMSettings(
        api_key=os.environ.get("LLM_API_KEY", ""),
        model=os.environ.get("LLM_MODEL", ""),
        base_url=os.environ.get("LLM_BASE_URL", ""),
        timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "15")),
    )
