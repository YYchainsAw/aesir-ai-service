"""Aesir AI 服务的运行时配置（pydantic-settings）。

若项目根目录存在 ``.env``，会在 import 时自动加载（依赖 ``python-dotenv``）。
所有配置项都有安全默认值，因此即使没有 ``.env`` 也能直接运行。

``get_settings()`` **每次调用都重新读环境变量**（不做缓存）：一是保持
「运行时可切换」语义，二是测试大量使用 ``monkeypatch.setenv`` 覆盖配置，
缓存会吞掉这些变化。
"""

from typing import Literal
from uuid import UUID

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """全部运行时配置项（环境变量前缀 AESIR_，LLM Provider 除外）。

    不用 ``env_file``：.env 已由 import 时的 ``load_dotenv()`` 注入进程环境，
    测试 ``monkeypatch.setenv/delenv`` 对本类的覆盖语义才与旧 getter 完全一致。
    """

    model_config = SettingsConfigDict(env_prefix="AESIR_", extra="ignore")

    # -- 服务监听 -----------------------------------------------------------
    service_host: str = "127.0.0.1"             # uvicorn 监听地址
    service_port: int = 8011                    # 默认监听端口；与 UE 两 Subsystem 代码默认值（8011）对齐，UE 侧零改动

    # -- 游戏档案（S3 / T028：一进程一游戏）-----------------------------------
    # 当前进程服务的游戏：决定加载 data/games/<game_id>/capability.yaml 游戏档案，
    # 并把人格注册表限制在 data/personas/<game_id>/ 之下。跨游戏角色请求返回 404，
    # 不回退默认角色、不混用另一游戏能力。多游戏并存时按游戏各起一个实例（独立端口）。
    game_id: str = "aesir"

    # -- v0.4 归属边界（单 worker；生产认证在第四步接入）-------------------
    scope_identity_backend: Literal["disabled", "development", "bearer"] = "disabled"
    scope_dev_player_id: UUID | None = None
    scope_dev_save_ids: list[UUID] = Field(default_factory=list)
    scope_legacy_enabled: bool = False  # 仅开发兼容；独立旧目录，不能读取 scoped 状态

    # -- 第四步事务存储与凭据（显式迁移，单 worker）---------------------
    scope_storage_backend: Literal["json", "sql"] = "json"
    scope_database_url: SecretStr = SecretStr("")
    scope_database_url_file: str = ""  # 可从站点根外0600文件读取，避免命令参数泄露
    scope_database_pool_size: int = Field(default=5, ge=1, le=10)
    scope_sqlite_test_mode: bool = False  # SQLite仅显式隔离测试，不作为MySQL故障回退
    scope_request_quota_per_minute: int = Field(default=120, ge=1)
    scope_upstream_quota_per_day: int = Field(default=200, ge=1)
    scope_sync_batch_limit: int = Field(default=50, ge=1, le=100)

    # -- 第三步请求编排（单 worker，保留原请求预算）----------------------
    scope_max_generation_concurrency: int = Field(default=2, ge=1, le=16)
    scope_request_queue_limit: int = Field(default=16, ge=1, le=32)
    scope_session_queue_limit: int = Field(default=4, ge=1, le=16)
    scope_request_state_limit: int = Field(default=1024, ge=1, le=16384)
    request_traces_dir: str = "data/runtime/request_traces"

    # -- 请求协调后端（阶段 0e：多 worker 部署用 Redis）----------------
    # memory（默认）：单进程 InMemoryScheduler，本地开发/单机测试开箱即跑。
    # redis：多 worker 共享全局槽/会话串行/排队深度；要求
    #   scope_storage_backend=sql——JSON 幂等在内存，多 worker 必然双执行，
    #   启动期直接拒绝（见下方校验器）。
    # 部署时显式设 AESIR_COORDINATION_BACKEND=redis + AESIR_SCOPE_STORAGE_BACKEND=sql。
    coordination_backend: Literal["memory", "redis"] = "memory"
    coordination_redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    coordination_lease_seconds: float = Field(default=30.0, gt=0)  # 槽/会话锁租约，崩溃自愈

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
    dialogue_signals_dir: str = "data/runtime/dialogue_signals"  # 对话信号埋点（RL 前置数据，JSONL 按角色分文件）
    agent_steps_dir: str = "data/runtime/agent_steps"  # agent/step 决策埋点（T38：SC-005/006/013 数据源）
    event_signals_dir: str = "data/runtime/event_signals"  # 事件幂等埋点（T38：SC-007 数据源）
    persona_reviews_dir: str = "data/persona_reviews"  # 外部人格包人工审核记录（S5/T30，入库、人写签字）
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_timeout_seconds: float = Field(default=15.0, alias="LLM_TIMEOUT_SECONDS")

    # -- LLM 熔断（SDD T084 / FR-041）----------------------------------------
    # 连续失败阈值：达到后进入 OPEN 状态，直接拒绝 LLM 调用并走 fallback
    llm_circuit_failure_threshold: int = 5
    # OPEN 状态持续时间（秒），之后进入 HALF_OPEN 试恢复
    llm_circuit_recovery_seconds: float = 60.0

    # -- 记忆体系（SDD US1 / T002）-------------------------------------------
    memory_root: str = "data/memory"            # 按角色分目录：data/memory/<npc_id>/，不入版本库
    memory_short_term_limit: int = 50           # 短期上下文条数上限（会话内滚动窗口）
    memory_summary_limit: int = 80              # 跨会话经历摘要条数上限
    memory_archive_limit: int = 40              # 长期档案条数上限（承诺/重大事件优先保留）
    memory_injection_budget: int = 12           # 单次生成注入 prompt 的记忆条数预算
    # -- 模糊印象层（主题 × 提及频率，替代逐字长期记忆）-----------------------
    memory_impression_limit: int = 200          # 印象主题数上限（超限淘汰最淡的）
    memory_impression_half_life_days: float = 7.0  # 印象权重半衰期（长期不提自然淡忘）
    memory_impression_inject_weight: float = 0.75  # 注入权重阈值：近期哪怕只提过 1 次也记得，随时间衰减后淡出
    memory_impression_deep_weight: float = 2.5    # 印象很深的权重阈值（多次提及/郑重声明 + 近期）
    memory_impression_injection_share: int = 5  # 单次注入的印象条数份额（不挤占记忆预算）
    memory_impression_salience_boost: float = 2.0  # 郑重声明的等效提及加成（首提即达注入阈值）
    memory_impression_salient_half_life_days: float = 28.0  # 显著话题半衰期（重要的事遗忘更慢）
    memory_impression_care_neutral: float = 50.0  # 在意值中性锚点：显著性加成按「偏离该值的程度」缩放（极爱与极厌都最在意）

    # -- 查证工具（SDD US6 / T067~T071）---------------------------------------
    tools_output_max_chars: int = 400            # 单次查证结果回填 prompt 的字符上限（FR-009 同纪律）
    tools_lookup_timeout_seconds: float = 2.0    # 查证总预算；超限降级为直接回应（FR-038）
    tools_max_rounds: int = 2                    # 模型侧轮次上限：1 轮查证 + 1 轮正式回复

    # -- 心跳（SDD US3 / T002）------------------------------------------------
    # 注：自主行为节流参数在 data/policy/agency_policy.yaml（不在此处）
    heartbeat_min_interval_seconds: float = 2.0  # /v1/agent 心跳最小间隔（限流用）

    # -- 关系体系（SDD US2 / T002）--------------------------------------------
    # 注：数值上下界在 app/schemas/relationship.py 的 _VALUE_BOUNDS
    relationship_root: str = "data/relationship"  # 按角色分目录：data/relationship/<npc_id>/，不入版本库
    relationship_initial: int = 20               # 初始关系数值（损坏/缺失时也回退到该值）
    relationship_daily_cap: int = 15              # 每日正向净变化上限（防刷）
    relationship_event_cooldown_seconds: float = 60.0  # 同类事件冷却窗口（窗口内重复不计分）
    relationship_dialogue_cooldown_seconds: float = 120.0  # 对话信号专属冷却（T45/#62：300→120s，让陪伴感涨得动）

    @model_validator(mode="after")
    def _reject_redis_with_json_storage(self) -> "Settings":
        # 用户拍板的硬边界：coordination_backend=redis 但 scope_storage_backend=json
        # 时启动即拒绝。JSON 幂等在内存，多 worker 必然双执行——留一个"也许能用"
        # 的坑，不如把边界写死。
        if self.coordination_backend == "redis" and self.scope_storage_backend == "json":
            raise ValueError(
                "coordination_backend=redis 要求 scope_storage_backend=sql："
                "JSON 幂等态留在单进程内存里，多 worker 共享调度必然导致同一逻辑"
                "请求被双执行。请改用 sql 存储后端，或把 coordination_backend 设回 memory。"
            )
        return self


def get_settings() -> Settings:
    """每次调用构造新实例：读当前环境变量（含 monkeypatch 的修改），不缓存。"""
    return Settings()
