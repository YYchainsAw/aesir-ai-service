"""稳定 ID 常量（协议 §5.2 命名：小写英文 + 点号分层）。

这些 ID 与 UE GameplayTag / DataAsset 主键一对一映射；规则解析器据此判断
能力目录是否允许某条命令，LLM 解析器据此校验响应是否越界。
"""

AGENT = "companion.eirin"
ABILITY_EXPLOSION = "ability.eirin.explosion"
ABILITY_BASIC_ATTACK = "ability.eirin.basic_attack"

SELECTOR_PRIMARY_HOSTILE = "encounter.primary_hostile"
SELECTOR_PLAYER = "party.player"

STATE_STUNNED = "state.stunned"
STATE_PHASE_TWO = "state.phase_two"