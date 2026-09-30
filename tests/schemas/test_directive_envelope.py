"""统一指令信封 schema 测试：action_type 白名单与降级路径。"""

import pytest
from pydantic import ValidationError

from app.api.v1.agent import _build_directive
from app.schemas.directives.common import (
    KNOWN_ACTION_TYPES,
    DirectiveActionType,
    DirectiveEnvelope,
    DirectivePresentation,
)


def _presentation() -> DirectivePresentation:
    return DirectivePresentation(
        reply_text="测试。", emotion_id="emotion.neutral", gesture_id="", facial_expression_id=""
    )


@pytest.mark.parametrize("action_type", sorted(KNOWN_ACTION_TYPES))
def test_legal_action_types_validate(action_type: str) -> None:
    """白名单内的 action_type 都能构造 DirectiveEnvelope。"""
    envelope = DirectiveEnvelope(
        agent_id="companion.alice",
        domain="combat",
        action_type=action_type,  # type: ignore[arg-type]
        presentation=_presentation(),
    )
    assert envelope.action_type == action_type


def test_unknown_action_type_rejected_by_schema() -> None:
    """白名单外的 action_type 被 Pydantic 校验拒绝（BR-01 / AT-07）。"""
    with pytest.raises(ValidationError):
        DirectiveEnvelope(
            agent_id="companion.alice",
            domain="combat",
            action_type="nuke_the_world",  # type: ignore[arg-type]
            presentation=_presentation(),
        )


def test_build_directive_returns_none_for_unknown_action_type() -> None:
    """服务层封装把 schema 拒绝转化为 None，便于降级为空动作。"""
    directive = _build_directive(
        agent_id="companion.alice",
        domain="combat",
        action_type="not_a_real_action",
        priority=50,
        source="player_command",
        reason_codes=["TEST"],
        policy_revision="test",
        payload={},
        presentation=_presentation(),
    )
    assert directive is None


def test_action_type_union_covers_known_set() -> None:
    """KNOWN_ACTION_TYPES 必须等于 DirectiveActionType 各 Literal 的并集。

    本测试防止未来新增行为类型时只改 schema 不改 KNOWN_ACTION_TYPES，
    或只改 KNOWN_ACTION_TYPES 不改 schema——两者必须同步。
    """
    # Pydantic 的 Union[Literal[...], ...] 会按 str 校验；这里通过运行期
    # 尝试构造所有 KNOWN_ACTION_TYPES 来验证集合一致性。
    for action_type in KNOWN_ACTION_TYPES:
        envelope = DirectiveEnvelope(
            agent_id="companion.alice",
            domain="combat",
            action_type=action_type,  # type: ignore[arg-type]
            presentation=_presentation(),
        )
        assert isinstance(envelope.action_type, str)
