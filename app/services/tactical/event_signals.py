"""事件幂等埋点（T38：SC-007 验收数据源）。

战斗通道与世界通道每处理一条事件，向
``data/runtime/event_signals/<game_id>/<companion_id>.jsonl`` 追加一条记录。

SC-007「幂等重复响应率 = 0」的脚本判定口径：同一 ``event_id`` 的第二次出现起，
``duplicate`` 必须全为 ``True``（网络重放）；若某条非首记录 ``duplicate=False``，
说明同一事件被独立评估了两次——幂等表被绕过，判 FAIL。

埋点是观测而非流程：任何写盘故障一律静默吞掉（绝不阻塞事件主流程）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings

_DEFAULT_GAME_ID = "aesir"


def record_event_resolved(
    companion_id: str,
    *,
    game_id: str = _DEFAULT_GAME_ID,
    channel: str = "",
    event_type: str = "",
    event_id: str = "",
    duplicate: bool = False,
    encounter_id: str = "",
) -> None:
    """追加一条事件处理记录（JSONL）；任何故障静默吞掉。

    每条经 ``_resolve`` 处理过的事件都写（duplicate True/False 都写），
    聚合层因此同时拥有分母（总事件数）与分子（重放数）。
    """
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "companion_id": companion_id,
            "channel": channel,
            "event_type": event_type,
            "event_id": event_id,
            "duplicate": bool(duplicate),
            "encounter_id": encounter_id,
        }
        root = Path(get_settings().event_signals_dir) / game_id
        root.mkdir(parents=True, exist_ok=True)
        with (root / f"{companion_id}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 埋点绝不阻塞事件主流程
        pass
