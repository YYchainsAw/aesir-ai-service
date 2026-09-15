"""社交域行为类型（SDD T049 / FR-045）。"""

from typing import Literal, TypeAlias

SocialActionTypes: TypeAlias = Literal[
    "express",     # 主动表达情绪/观点
    "self_talk",   # 自言自语
]

# payload 键：topic（话题代号）、gaze_target_id（注视目标）
