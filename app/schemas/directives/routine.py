"""日常域行为类型（SDD T049 / FR-045）。"""

from typing import Literal, TypeAlias

RoutineActionTypes: TypeAlias = Literal[
    "rest",         # 休整
    "eat",          # 进食
    "repair_gear",  # 修补装备
]

# payload 键：duration_seconds（持续秒数）
