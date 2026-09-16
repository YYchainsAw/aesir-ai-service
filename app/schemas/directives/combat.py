"""战斗域行为类型（SDD T049 / FR-045）。

只声明 action_type 白名单与关键 payload 键；信封 ``DirectiveEnvelope`` 保持
宽松（``action_type: str``），白名单校验在服务层行为目录完成（T051）。
与 v0.1 ``TacticalOrder`` 的语义对应关系见 ue-protocol-contract-v0.1.md。
"""

from typing import Literal, TypeAlias

# 战斗行为（v0.1 战术决策的动作类型）
CombatActionTypes: TypeAlias = Literal[
    "major_heal",   # 强效治疗
    "quick_heal",   # 快速治疗
    "shield",       # 护盾
    "burst",        # 爆发输出
    "retreat",      # 撤退自保
]

# payload 键：skill_id（能力 ID）、target_id（目标，须为快照中出现过的 ID）
