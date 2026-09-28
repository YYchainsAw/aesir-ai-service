"""非战斗状态下的队友对话协议。

首版只提供固定模拟回复，用于让 UE 先完成字幕、表情与动作提示的联调。
后续接入 LLM 时保持本文件中的请求/响应结构不变。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.world_context import WorldContext


class CompanionDialogueRequest(BaseModel):
    """玩家发送给非战斗队友的文字消息。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500, description="玩家输入或 ASR 转写的文本")
    companion_id: str = Field(
        default="companion.alice",
        min_length=1,
        max_length=100,
        description="UE 中队友的稳定 ID",
    )
    game_state: Literal["exploration", "conversation"] = "exploration"
    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description=(
            "会话标识（UE 侧生成并在同一轮对话中复用）。传入时服务端维护最近 "
            "N 轮滚动记忆并注入 LLM；缺省时本请求完全无状态（v0.1 行为不变）。"
        ),
    )
    # US6（T069）：随本轮对话携带的世界快照（只读输入）。查证工具据此回答战况、
    # 环境与自身状态类问题；缺省时这些工具按「无据可查」明确表示不确定。
    # 可选字段，老请求不带它时行为与 v0.1 完全一致。
    world_context: WorldContext | None = None


class CompanionDialogueResponse(BaseModel):
    """UE 可直接映射为字幕、表情和 Montage 的对话响应。"""

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["0.1"] = "0.1"
    companion_id: str
    session_id: str | None = None
    reply_text: str
    emotion_id: str
    gesture_id: str
    facial_expression_id: str
    interruptible: bool = True
    source: Literal["mock", "llm", "fallback"] = "mock"
    # US2（T042）：当前关系阶段（distant/neutral/friendly/close）；关系体系
    # 故障降级时为空字符串——UE 不应依赖该字段做表现逻辑。
    relationship_stage: str = ""
    # FIX-05：关系阶段中文展示名（疏远/平常/友好/亲密），供 UI 直接展示。
    relationship_stage_display: str = ""
    # 对话推动关系（2026-09-22）：本轮玩家发言的情感质量实际造成的关系增减
    # （+1/+2/-1/-2，冷却或日上限吃掉则为 0）。阶段变化自下一轮生效——
    # relationship_stage 读的是本轮生成前的值。
    relationship_delta: int = 0
    # US7（T076）链路信息：人设 YAML 的 profile_version 与本轮实际注入的
    # 记忆条数（按通道：长期记忆 / 模糊印象）。缺省空——UE 不应依赖。
    persona_revision: str = ""
    memory_layers: dict[str, int] = Field(default_factory=dict)
