"""表达一致性校验测试（SDD T083 / FR-002 / FR-003）。

覆盖：出戏术语拦截、禁忌表达拦截、虚构事实信号拦截、策略加载、
记忆支撑下的虚构信号放行、以及 LLM 服务层的重试/回退路径。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.companion_dialogue import CompanionDialogueRequest
from app.services.companion.llm_dialogue_service import LLMCompanionDialogueService
from app.services.companion import style_guard
from app.services.companion.style_guard import StylePolicy, StyleViolation, check_reply, get_style_policy


# ---------------------------------------------------------------------------
# 策略加载
# ---------------------------------------------------------------------------

def test_style_policy_loads_from_yaml() -> None:
    policy = get_style_policy()
    assert policy.revision
    assert "指令" in policy.meta_terms
    assert "你是我的" in policy.forbidden_expressions
    assert "你说过" in policy.fabrication_signals


def test_style_policy_rejects_corrupt_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "style_policy.yaml"
    bad.write_text("meta_terms: not_a_list", encoding="utf-8")

    with pytest.raises(style_guard.StylePolicyError, match="must be a list"):
        StylePolicy.load(bad)


def test_style_policy_rejects_empty_term(tmp_path: Path) -> None:
    bad = tmp_path / "style_policy.yaml"
    bad.write_text(
        "revision: test\nmeta_terms:\n  - \"\"\nforbidden_expressions: []\nfabrication_signals: []",
        encoding="utf-8",
    )

    with pytest.raises(style_guard.StylePolicyError, match="non-empty string"):
        StylePolicy.load(bad)


# ---------------------------------------------------------------------------
# 直接命中校验
# ---------------------------------------------------------------------------

def test_meta_term_violation() -> None:
    violations = check_reply("这是系统指令，请执行。")
    assert any(v.category == "meta_term" and v.matched_term == "指令" for v in violations)


def test_multiple_meta_terms_reported() -> None:
    violations = check_reply("模型返回协议响应给客户端。")
    categories = {v.matched_term for v in violations if v.category == "meta_term"}
    assert {"模型", "协议", "客户端"} <= categories


def test_forbidden_expression_violation() -> None:
    violations = check_reply("你是我的，不准跟别人走。")
    assert any(v.category == "forbidden_expression" for v in violations)


def test_clean_reply_passes() -> None:
    assert check_reply("今天天气不错，要不要出去走走？") == []


def test_empty_text_passes() -> None:
    assert check_reply("") == []


# ---------------------------------------------------------------------------
# 虚构事实信号
# ---------------------------------------------------------------------------

def test_fabrication_signal_without_memory_is_violation() -> None:
    violations = check_reply("你说过要带我去看海，当然记得。")
    assert any(v.category == "fabrication_signal" for v in violations)


def test_fabrication_signal_with_memory_is_allowed() -> None:
    fake_memory = object()  # check_reply 只看列表是否非空
    violations = check_reply(
        "你说过要带我去看海，当然记得。",
        injected_memories=[fake_memory],
    )
    assert not any(v.category == "fabrication_signal" for v in violations)


def test_fabrication_signal_with_impression_is_allowed() -> None:
    fake_impression = object()
    violations = check_reply(
        "你答应过的事我不会忘。",
        injected_impressions=[fake_impression],
    )
    assert not any(v.category == "fabrication_signal" for v in violations)


def test_fabrication_check_can_be_disabled() -> None:
    policy = StylePolicy(
        revision="test",
        meta_terms=frozenset(),
        forbidden_expressions=frozenset(),
        fabrication_signals=frozenset(["你说过"]),
        require_memory_for_fabrication_signals=False,
    )
    violations = check_reply("你说过要带我去看海。", policy=policy)
    assert not any(v.category == "fabrication_signal" for v in violations)


# ---------------------------------------------------------------------------
# LLM 服务层集成
# ---------------------------------------------------------------------------

class _StubLLMClient:
    """可配置返回 payload 的 LLM 测试替身。"""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    def generate_json(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2):
        self.calls += 1
        return self.payload


def _valid_payload(reply_text: str) -> dict[str, object]:
    return {
        "reply_text": reply_text,
        "emotion_id": "emotion.bright",
        "gesture_id": "gesture.cheerful_idle",
        "facial_expression_id": "face.bright_smile",
        "interruptible": True,
        "topics": [],
        "facts": [],
        "reply_topics": [],
        "relationship_signal": "none",
        "salient": False,
    }


def test_reply_passes_style_guard() -> None:
    service = LLMCompanionDialogueService(_StubLLMClient(_valid_payload("今天天气真好。")))
    response = service.reply(CompanionDialogueRequest(text="你好"))
    assert response.reply_text == "今天天气真好。"


def test_reply_retries_once_on_style_violation() -> None:
    """首次回复违规 → 重试一次；第二次通过则正常返回。"""
    bad = _valid_payload("这是系统指令。")
    good = _valid_payload("我在呢，想聊什么？")
    stub = _StubLLMClient(bad)
    # 用同一个 payload 引用，通过 monkeypatch 第二次返回 good
    stub.payload = bad

    call_count = {"n": 0}
    original_generate = stub.generate_json

    def counting_generate(*, system_prompt, user_prompt, temperature=0.2):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return bad
        return good

    stub.generate_json = counting_generate

    service = LLMCompanionDialogueService(stub)
    response = service.reply(CompanionDialogueRequest(text="你好"))
    assert call_count["n"] == 2
    assert response.reply_text == "我在呢，想聊什么？"


def test_reply_falls_back_after_two_style_violations() -> None:
    """连续两次风格违规 → 抛 LLMClientError，由 dialogue_service 回退 mock。"""
    from app.services.llm.client import LLMClientError

    bad = _valid_payload("这是系统指令。")
    service = LLMCompanionDialogueService(_StubLLMClient(bad))

    with pytest.raises(LLMClientError, match="style guard"):
        service.reply(CompanionDialogueRequest(text="你好"))


def test_reply_no_fabrication_violation_when_memory_injected() -> None:
    """注入记忆时，'你说过' 类表述被放行。"""
    payload = _valid_payload("你说过怕高，靠近悬崖我会提醒你。")
    service = LLMCompanionDialogueService(_StubLLMClient(payload))
    from app.schemas.memory import MemoryEntry

    memory = MemoryEntry(
        content="玩家怕高",
        importance="normal",
        source="player_statement",
        game_time="2026-09-24T12:00:00Z",
        real_time="2026-09-24T12:00:00Z",
    )
    response = service.reply(
        CompanionDialogueRequest(text="我怕高"),
        memories=[memory],
    )
    assert response.reply_text == "你说过怕高，靠近悬崖我会提醒你。"
