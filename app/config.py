"""Aesir AI 服务的运行时配置（pydantic-settings）。

若项目根目录存在 ``.env``，会在 import 时自动加载（依赖 ``python-dotenv``）。
所有配置项都有安全默认值，因此即使没有 ``.env`` 也能直接运行。

``get_settings()`` **每次调用都重新读环境变量**（不做缓存）：一是保持
「运行时可切换」语义，二是测试大量使用 ``monkeypatch.setenv`` 覆盖配置，
缓存会吞掉这些变化。
"""

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """全部运行时配置项（环境变量前缀 AESIR_，LLM Provider 除外）。

    不用 ``env_file``：.env 已由 import 时的 ``load_dotenv()`` 注入进程环境，
    测试 ``monkeypatch.setenv/delenv`` 对本类的覆盖语义才与旧 getter 完全一致。
    """

    model_config = SettingsConfigDict(env_prefix="AESIR_", extra="ignore")

    # -- 后端选择 -----------------------------------------------------------
    parser_backend: str = "rule"                # rule | llm
    companion_backend: str = "mock"             # mock | llm
    asr_backend: str = "mock"                   # mock | faster_whisper
    tactical_policy: str = "rule"               # rule | rl（rl 仅占位，见总策划书 Phase 4）
    intent_backend: str = "rule"                # rule | llm（/v1/tactical/command 的意图解析后端）
    dialogue_history_turns: int = 10            # 会话记忆滚动窗口（session_id 维度，0 = 关闭记忆）

    # -- ASR ----------------------------------------------------------------
    asr_mock_text: str = ""                      # mock 转写固定文本；空 = 没转出命令
    asr_model: str = "small"                     # 8GB 显存够用、中文准确、延迟低
    asr_device: str = "auto"                     # auto：有 CUDA 用 GPU，否则 CPU
    asr_compute_type: str = "int8_float16"       # CUDA 加速；CPU 自动退化 int8
    asr_language: str = "zh"                     # 跳过语言检测省开销

    # -- 回执与 LLM Provider -------------------------------------------------
    receipts_dir: str = "data/rl/executions"    # executions JSONL 落盘目录（草案 §7）
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_timeout_seconds: float = Field(default=15.0, alias="LLM_TIMEOUT_SECONDS")


def get_settings() -> Settings:
    """每次调用构造新实例：读当前环境变量（含 monkeypatch 的修改），不缓存。"""
    return Settings()
