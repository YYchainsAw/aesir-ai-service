"""单一指令体系（SDD 章程原则 VI / FR-045）。

所有下发指令使用同一信封 + 按行为类型判别的联合类型；
实现按活动域分文件放本目录，禁止建立平行的多套指令体系。
"""

from app.schemas.directives.combat import CombatActionTypes
from app.schemas.directives.common import (
    DIRECTIVE_PROTOCOL_VERSION,
    KNOWN_ACTION_TYPES,
    DirectiveActionType,
    DirectiveDomain,
    DirectiveEnvelope,
    DirectiveExpires,
    DirectivePresentation,
    ExpiresAtEncounterEnd,
    ExpiresBeforeSeconds,
    ExpiresImmediate,
)
from app.schemas.directives.interaction import InteractionActionTypes
from app.schemas.directives.movement import MovementActionTypes
from app.schemas.directives.routine import RoutineActionTypes
from app.schemas.directives.social import SocialActionTypes

__all__ = [
    "CombatActionTypes",
    "DIRECTIVE_PROTOCOL_VERSION",
    "KNOWN_ACTION_TYPES",
    "DirectiveActionType",
    "DirectiveDomain",
    "DirectiveEnvelope",
    "DirectiveExpires",
    "DirectivePresentation",
    "ExpiresAtEncounterEnd",
    "ExpiresBeforeSeconds",
    "ExpiresImmediate",
    "InteractionActionTypes",
    "MovementActionTypes",
    "RoutineActionTypes",
    "SocialActionTypes",
]

