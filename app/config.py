"""Aesir AI 服务的运行时配置。

若项目根目录存在 ``.env``，会在 import 时自动加载（依赖 ``python-dotenv``）。
所有配置项都有安全默认值，因此即使没有 ``.env`` 也能直接运行。
"""

import os

from dotenv import load_dotenv

load_dotenv()


def get_parser_backend() -> str:
    """返回当前生效的命令解析后端。

    每次调用时读取（而非在 import 时读取），方便在运行时切换，也便于测试时
    覆盖环境变量。取值：``rule``（默认）或 ``llm``。
    """
    return os.environ.get("AESIR_PARSER_BACKEND", "rule")


def get_llm_base_url() -> str:
    """LLM Chat Completions 的基础地址（OpenAI 兼容）。默认 DeepSeek。"""
    return os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")


def get_llm_model() -> str:
    """LLM 模型名。默认 DeepSeek 的 deepseek-chat。"""
    return os.environ.get("LLM_MODEL", "deepseek-chat")


def get_llm_api_key() -> str | None:
    """LLM API key。未配置时返回 None，解析器会因此抛 LLMNotConfiguredError。"""
    return os.environ.get("LLM_API_KEY")


def get_llm_timeout() -> float:
    """LLM 请求超时（秒）。"""
    return float(os.environ.get("LLM_TIMEOUT", "30"))