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


def get_asr_model() -> str:
    """faster-whisper 模型名（按需下载）。默认 ``small``：8GB 显存够用、中文准确、延迟低。"""
    return os.environ.get("AESIR_ASR_MODEL", "small")


def get_asr_device() -> str:
    """推理设备。默认 ``auto``：有 CUDA 用 GPU，否则 CPU，避免本地未装 CUDA 后端直接崩。"""
    return os.environ.get("AESIR_ASR_DEVICE", "auto")


def get_asr_compute_type() -> str:
    """量化类型。默认 ``int8_float16``：CUDA 上加速、CPU 自动退化为 int8。"""
    return os.environ.get("AESIR_ASR_COMPUTE_TYPE", "int8_float16")


def get_asr_language() -> str:
    """转写语言，跳过语言检测省开销。默认中文 ``zh``。"""
    return os.environ.get("AESIR_ASR_LANGUAGE", "zh")


def get_tactical_policy() -> str:
    """返回战术决策策略后端：``rule``（默认）或 ``rl``。

    本阶段 ``rl`` 仅为占位：``/v1/tactical/resolve`` 恒走规则策略并在
    observability 中保留 rl 标记（规则系统始终保留，对应总策划书 Phase 4）。
    """
    return os.environ.get("AESIR_TACTICAL_POLICY", "rule")


def get_receipts_dir() -> str:
    """executions 回执 JSONL 落盘目录（v0.2 草案 §7 的真实数据采集通道）。"""
    return os.environ.get("AESIR_RECEIPTS_DIR", os.path.join("data", "rl", "executions"))


def get_llm_settings() -> LLMSettings:
    """读取两个业务链路共用的 LLM Provider 配置。"""
    return LLMSettings(
        api_key=os.environ.get("LLM_API_KEY", ""),
        model=os.environ.get("LLM_MODEL", ""),
        base_url=os.environ.get("LLM_BASE_URL", ""),
        timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "15")),
    )
