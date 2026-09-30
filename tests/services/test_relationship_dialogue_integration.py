"""关系接入对话链路测试（SDD T040 / T042 / FR-016）。"""

from __future__ import annotations

from app.schemas.companion_dialogue import CompanionDialogueRequest
from app.services.companion import dialogue_service
from app.services.companion.llm_dialogue_service import _build_system_prompt
from app.services.companion.profile_repository import get_profile
from app.services.relationship.state import RelationshipStoreError, reset_relationship_stores


def test_chat_response_carries_relationship_stage(monkeypatch) -> None:
    """T042：对话响应回带当前关系阶段。"""
    monkeypatch.setattr(dialogue_service, "_relationship_stage", lambda cid, *, game_id="aesir": "close")
    response = dialogue_service.create_dialogue_reply(
        CompanionDialogueRequest(text="今天休息一下吧？")
    )
    assert response.relationship_stage == "close"


def test_system_prompt_injects_stage_persona() -> None:
    """T040：阶段化称呼与语气偏移进入 LLM 系统提示。"""
    prompt = _build_system_prompt(get_profile(), relationship_stage="distant")
    assert "Current relationship stage: distant" in prompt
    assert "旅行者" in prompt


def test_system_prompt_injects_stage_boundary() -> None:
    """阶段硬边界进入 prompt，并声明与基础人设冲突时以它为准。

    只偏移语气时，基础人设的「暗藏情愫」照常生效——distant 阶段会出现
    「一边叫旅行者、一边聊两人合披一块油布」的割裂（2026-09-21 实测）。
    """
    prompt = _build_system_prompt(get_profile(), relationship_stage="distant")
    assert "Stage hard boundary" in prompt
    assert "THIS wins" in prompt
    assert "不表露好感" in prompt


def test_system_prompt_unknown_stage_uses_baseline() -> None:
    """未知/空阶段沿用基线人设，不注入关系块（降级思路）。"""
    prompt = _build_system_prompt(get_profile(), relationship_stage="")
    assert "Current relationship stage" not in prompt


def test_stage_lookup_degrades_to_empty(monkeypatch) -> None:
    """关系体系故障时对话不中断（FR-018 同思路的链路级降级）。"""
    from app.services.relationship import state as rel_state

    def _boom(npc_id, *, game_id="aesir", root=None):
        raise RelationshipStoreError("disk on fire")

    monkeypatch.setattr(rel_state, "get_relationship_store", _boom)
    assert dialogue_service._relationship_stage("companion.alice", game_id="aesir") == ""
    reset_relationship_stores()


# -- 对话推动关系（2026-09-22）------------------------------------------------
class _StubSignalLLM:
    """返回固定情感质量信号的 LLM 替身。"""

    def __init__(self, signal: str) -> None:
        self.signal = signal

    def generate_json(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2):
        return {
            "action": "reply",
            "reply_text": "嗯，我在听。",
            "emotion_id": "emotion.pleased",
            "gesture_id": "gesture.small_wave",
            "facial_expression_id": "face.gentle_smile",
            "interruptible": True,
            "topics": [],
            "facts": [],
            "reply_topics": [],
            "relationship_signal": self.signal,
            "salient": False,
        }


def _chat_with_signal(monkeypatch, signal: str, text: str):
    """走 LLM 后端发一轮对话，LLM 顺带返回指定的关系信号。"""
    from app.services.companion import llm_dialogue_service as llm_module

    monkeypatch.setenv("AESIR_COMPANION_BACKEND", "llm")
    monkeypatch.setattr(llm_module, "create_llm_client", lambda: _StubSignalLLM(signal))
    return dialogue_service.create_dialogue_reply(CompanionDialogueRequest(text=text))


def _relationship_value() -> int:
    from app.services.relationship.state import get_relationship_store

    return get_relationship_store("companion.alice").state().value


def test_warm_signal_raises_relationship(monkeypatch) -> None:
    """玩家真诚关心 → +1 落库且响应回带 delta（对话终于聊得动关系）。"""
    response = _chat_with_signal(monkeypatch, "warm", "今天辛苦你了。")
    assert response.relationship_delta == 1
    assert _relationship_value() == 21  # 初值 20


def test_dialogue_cooldown_blocks_rapid_repeat(monkeypatch) -> None:
    """对话专属冷却（默认 300 秒）：连点第二句不再计分（防刷）。"""
    first = _chat_with_signal(monkeypatch, "warm", "谢谢你陪我。")
    second = _chat_with_signal(monkeypatch, "warm", "真的很感谢你。")
    assert first.relationship_delta == 1
    assert second.relationship_delta == 0  # 冷却窗口内同类信号不计分
    assert _relationship_value() == 21


def test_hurtful_signal_lowers_relationship(monkeypatch) -> None:
    """恶意伤人 → -2（负向不设上限——疏远不需要配额）。"""
    response = _chat_with_signal(monkeypatch, "hurtful", "你就是个累赘。")
    assert response.relationship_delta == -2
    assert _relationship_value() == 18


def test_none_and_mock_paths_do_not_move_relationship(monkeypatch) -> None:
    """普通闲聊（none）与 mock 路径不动关系——宁漏勿滥。"""
    llm_response = _chat_with_signal(monkeypatch, "none", "今天天气不错。")
    assert llm_response.relationship_delta == 0

    mock_response = dialogue_service.create_dialogue_reply(
        CompanionDialogueRequest(text="今天天气不错。")
    )
    assert mock_response.relationship_delta == 0
    assert _relationship_value() == 20


def test_several_warm_exchanges_cross_into_neutral(monkeypatch) -> None:
    """校准断言（半天~一天一档）：约 5 轮真诚交流跨入 neutral(25)。"""

    def _warm_round(i: int) -> None:
        monkeypatch.setenv("AESIR_COMPANION_BACKEND", "llm")
        from app.services.companion import llm_dialogue_service as llm_module

        monkeypatch.setattr(llm_module, "create_llm_client", lambda: _StubSignalLLM("warm"))
        # 绕开真实冷却（时间戳用分散的过去时刻），只验证校准节奏
        monkeypatch.setenv("AESIR_RELATIONSHIP_DIALOGUE_COOLDOWN_SECONDS", "0")
        dialogue_service.create_dialogue_reply(CompanionDialogueRequest(text=f"谢谢你，第{i}轮。"))

    for i in range(5):
        _warm_round(i)

    from app.services.relationship.state import get_relationship_store

    state = get_relationship_store("companion.alice").state()
    assert state.value == 25
    assert state.stage == "neutral"


def test_relationship_failure_keeps_dialogue_alive(monkeypatch) -> None:
    """关系层故障 → 对话照常返回且 delta 为 0（FR-011 同纪律）。"""
    from app.services.relationship import state as rel_state

    def _boom(npc_id, *, game_id="aesir", root=None):
        raise RelationshipStoreError("disk on fire")

    monkeypatch.setattr(rel_state, "get_relationship_store", _boom)
    response = _chat_with_signal(monkeypatch, "warm", "谢谢你。")
    assert response.reply_text
    assert response.relationship_delta == 0
    reset_relationship_stores()
