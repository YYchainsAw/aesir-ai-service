"""agent/step 决策埋点（T38：SC-005/006/013 验收数据源）。

每轮 ``/v1/agent/step`` 结束后向 ``data/runtime/agent_steps/<game_id>/<companion_id>.jsonl``
追加一条记录，承载事实上的「决策可解释载体」——``AgentStepObservability`` 与
``reason_codes``（代码里并不存在独立的 decision_trace 对象，它们就是）。

一份埋点同时喂三项验收：

- **SC-005 自主行为类型 ≥ 8 类**：自主步（reason_codes 含 ``ARB_WON:`` 前缀）
  的 ``directive_action_type`` 去重分布；
- **SC-006 自主行为重复率 = 0**：自主步按时间排序后相邻 action_type 的重复比例；
- **SC-013 决策可解释覆盖率 100%**：``reason_codes`` 非空记录占总步数比例。

埋点是观测而非流程：任何写盘故障一律静默吞掉（同 dialogue_signals 纪律，
绝不因埋点阻塞 agent/step 主流程）。

v0.4 作用域请求的日志写入失败向外传播，由请求协调器记录未知提交结果。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.scoped.context import current_scope
from app.scoped.storage import signal_directory, signal_metadata, guarded_commit, unavailable

_DEFAULT_GAME_ID = "aesir"


@guarded_commit
def record_agent_step(
    companion_id: str,
    *,
    game_id: str = _DEFAULT_GAME_ID,
    scene: str = "",
    action: str = "",
    directive_action_type: str | None = None,
    reason_codes: list[str] | None = None,
    observability_source: str = "",
    degraded: bool = False,
) -> None:
    """追加一条 agent/step 决策记录（JSONL）；任何故障静默吞掉。

    ``directive_action_type`` 仅在本步产出 directive 时有值（空响应步为 None）。
    """
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "companion_id": companion_id,
            "scene": scene,
            "action": action,
            "directive_action_type": directive_action_type,
            "reason_codes": list(reason_codes or []),
            "observability_source": observability_source,
            "degraded": bool(degraded),
        }
        root = signal_directory(get_settings().agent_steps_dir, game_id)
        record.update(signal_metadata())
        root.mkdir(parents=True, exist_ok=True)
        with (root / f"{companion_id}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as error:  # noqa: BLE001 - 埋点绝不阻塞 agent/step 主流程
        if current_scope():
            raise unavailable() from error
        pass
