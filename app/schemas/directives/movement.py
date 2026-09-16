"""移动域行为类型（SDD T049 / FR-045）。"""

from typing import Literal, TypeAlias

MovementActionTypes: TypeAlias = Literal[
    "follow",        # 跟随玩家
    "move_to",       # 移动到目标位置
    "wait",          # 原地等待
    "retreat_move",  # 撤退移动
]

# payload 键：object_id（快照中出现过的对象 ID）或 x/y/z（坐标字符串）
