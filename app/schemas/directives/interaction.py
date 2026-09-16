"""交互域行为类型（SDD T049 / FR-045）。"""

from typing import Literal, TypeAlias

InteractionActionTypes: TypeAlias = Literal[
    "inspect",       # 查看/打量附近物件
    "interact",      # 与物件交互
    "pickup",        # 拾取物品
    "observe",       # 静止观察（注视目标）
    "alert_player",  # 发现线索提醒玩家
]

# payload 键：object_id（快照中出现过的对象 ID）
