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
    receipts_dir: str = "data/runtime/command_service/executions"
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_timeout_seconds: float = Field(default=15.0, alias="LLM_TIMEOUT_SECONDS")

    # -- 记忆体系（SDD US1 / T002）-------------------------------------------
    memory_root: str = "data/memory"            # 按角色分目录：data/memory/<npc_id>/，不入版本库
    memory_short_term_limit: int = 50           # 短期上下文条数上限（会话内滚动窗口）
    memory_summary_limit: int = 80              # 跨会话经历摘要条数上限
    memory_archive_limit: int = 40              # 长期档案条数上限（承诺/重大事件优先保留）
    memory_injection_budget: int = 12           # 单次生成注入 prompt 的记忆条数预算
    # -- 模糊印象层（主题 × 提及频率，替代逐字长期记忆）-----------------------
    memory_impression_limit: int = 200          # 印象主题数上限（超限淘汰最淡的）
    memory_impression_half_life_days: float = 7.0  # 印象权重半衰期（长期不提自然淡忘）
    memory_impression_min_mentions: int = 3     # 达到该提及次数才注入 prompt
    memory_impression_injection_share: int = 3  # 单次注入的印象条数份额（不挤占记忆预算）
    memory_impression_salience_boost: float = 2.0  # 郑重声明的等效提及加成（首提即达注入阈值）
    memory_impression_salient_half_life_days: float = 28.0  # 显著话题半衰期（重要的事遗忘更慢）
    memory_impression_care_neutral: float = 50.0  # 在意值中性锚点：显著性加成按「偏离该值的程度」缩放（极爱与极厌都最在意）

    # -- 心跳（SDD US3 / T002）------------------------------------------------
    # 注：自主行为节流参数在 data/policy/agency_policy.yaml（不在此处）
    heartbeat_min_interval_seconds: float = 2.0  # /v1/agent 心跳最小间隔（限流用）

    # -- 关系体系（SDD US2 / T002）--------------------------------------------
    # 注：数值上下界在 app/schemas/relationship.py 的 _VALUE_BOUNDS
    relationship_root: str = "data/relationship"  # 按角色分目录：data/relationship/<npc_id>/，不入版本库
    relationship_initial: int = 20               # 初始关系数值（损坏/缺失时也回退到该值）
    relationship_daily_cap: int = 15              # 每日正向净变化上限（防刷）
    relationship_event_cooldown_seconds: float = 60.0  # 同类事件冷却窗口（窗口内重复不计分）


def get_settings() -> Settings:
    """每次调用构造新实例：读当前环境变量（含 monkeypatch 的修改），不缓存。"""
    return Settings()
