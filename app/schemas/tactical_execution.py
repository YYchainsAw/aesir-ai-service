"""v0.2/v0.3 战术执行回执 `ExecutionReceipt`（草案 §7 / EXT-04）。

UE 对 ``DecisionAction.order_id`` 的执行回执：首版仅落 JSONL 供排查与后续
RL 数据集筛选，不自动用于训练（草案 §7：「不将该数据自动用于训练」）。
v0.3 起支持批量上传：同一端点同时兼容 ``{"receipt": {...}}`` 与
``{"receipts": [...]}``。
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.tactical_decision import PROTOCOL_VERSION_V02

ReceiptResult = Literal["accepted", "executed", "rejected", "expired", "cancelled"]


class ExecutionReceipt(BaseModel):
    """UE 侧对单个 order 的执行结果回执。"""

    protocol_version: Literal["0.2"] = PROTOCOL_VERSION_V02
    order_id: str = Field(min_length=1)
    result: ReceiptResult
    encounter_id: str = Field(min_length=1)
    request_id: str = ""  # 草案 §7 示例含此字段；UE 可选回填
    reason_code: str = ""  # UE 侧失败原因，如 UE_EXECUTOR_BUSY / UE_CAST_INTERRUPTED
    agent_id: str = ""
    ability_id: str | None = None
    reported_at: str = ""  # UE 侧报告时间（ISO-8601 UTC），可选
    received_at: str = ""  # 服务端受理时间；缺省时由服务端补
    policy_revision: str = ""  # UE 侧可选回填，便于区分 rule/rl 数据
    sequence: int | None = Field(default=None, ge=0)


class ExecutionReceiptRequest(BaseModel):
    """回执请求信封：单条 ``receipt`` 与批量 ``receipts`` 二选一。"""

    receipt: ExecutionReceipt | None = None
    receipts: list[ExecutionReceipt] | None = None

    @model_validator(mode="after")
    def _check_exactly_one(self) -> "ExecutionReceiptRequest":
        has_single = self.receipt is not None
        has_batch = self.receipts is not None and len(self.receipts) > 0
        if not has_single and not has_batch:
            raise ValueError("必须提供 receipt 或 receipts 之一")
        if has_single and has_batch:
            raise ValueError("receipt 与 receipts 不能同时提供")
        return self
