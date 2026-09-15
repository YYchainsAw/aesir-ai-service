"""关系接入对话链路测试（SDD T040 / T042 / FR-016）。"""

from __future__ import annotations

from app.schemas.companion_dialogue import CompanionDialogueRequest
from app.services.companion import dialogue_service
from app.services.companion.llm_dialogue_service import _build_system_prompt
from app.services.companion.profile_repository import get_profile
from app.services.relationship.state import RelationshipStoreError, reset_relationship_stores


def test_chat_response_carries_relationship_stage(monkeypatch) -> None:
    """T042：对话响应回带当前关系阶段。"""
    monkeypatch.setattr(dialogue_service, "_relationship_stage", lambda cid: "close")
    response = dialogue_service.create_dialogue_reply(
        CompanionDialogueRequest(text="今天休息一下吧？")
    )
    assert response.relationship_stage == "close"


def test_system_prompt_injects_stage_persona() -> None:
    """T040：阶段化称呼与语气偏移进入 LLM 系统提示。"""
    prompt = _build_system_prompt(get_profile(), relationship_stage="distant")
    assert "Current relationship stage: distant" in prompt
    assert "旅行者" in prompt


def test_system_prompt_unknown_stage_uses_baseline() -> None:
    """未知/空阶段沿用基线人设，不注入关系块（降级思路）。"""
    prompt = _build_system_prompt(get_profile(), relationship_stage="")
    assert "Current relationship stage" not in prompt


def test_stage_lookup_degrades_to_empty(monkeypatch) -> None:
    """关系体系故障时对话不中断（FR-018 同思路的链路级降级）。"""
    from app.services.relationship import state as rel_state

    def _boom(npc_id, *, root=None):
        raise RelationshipStoreError("disk on fire")

    monkeypatch.setattr(rel_state, "get_relationship_store", _boom)
    assert dialogue_service._relationship_stage("companion.alice") == ""
    reset_relationship_stores()
