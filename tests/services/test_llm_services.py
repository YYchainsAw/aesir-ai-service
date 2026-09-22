import json
from typing import Any

import pytest

from app.schemas.companion_dialogue import CompanionDialogueRequest
from app.services.companion.llm_dialogue_service import LLMCompanionDialogueService
from app.services.llm.client import LLMClientError
from app.services.parsers.llm import LLMCommandParser


class StubLLMClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.system_prompt = ""
        self.user_prompt = ""

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self.payload


def test_companion_llm_service_validates_and_returns_ue_ids() -> None:
    service = LLMCompanionDialogueService(
        StubLLMClient(
            {
                "reply_text": "当然可以，和你一起出发总不会无聊。",
                "emotion_id": "emotion.pleased",
                "gesture_id": "gesture.enthusiastic_nod",
                "facial_expression_id": "face.gentle_smile",
                "interruptible": True,
            }
        )
    )

    response = service.reply(CompanionDialogueRequest(text="我们出发吧。"))

    assert response.source == "llm"
    assert response.companion_id == "companion.alice"
    assert response.emotion_id == "emotion.pleased"


def test_companion_llm_service_rejects_unknown_ue_id() -> None:
    service = LLMCompanionDialogueService(
        StubLLMClient(
            {
                "reply_text": "这可不是我会用的表情。",
                "emotion_id": "emotion.not_registered",
                "gesture_id": "gesture.cheerful_idle",
                "facial_expression_id": "face.bright_smile",
                "interruptible": True,
            }
        )
    )

    with pytest.raises(LLMClientError, match="unknown emotion ID"):
        service.reply(CompanionDialogueRequest(text="测试"))


def test_companion_llm_prompt_injects_full_persona_and_examples() -> None:
    """方案 A 回归：prompt 必须包含人设全量字段与 few-shot 示例。"""
    stub = StubLLMClient(
        {
            "reply_text": "好呀。",
            "emotion_id": "emotion.bright",
            "gesture_id": "gesture.cheerful_idle",
            "facial_expression_id": "face.bright_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="聊点什么吧"))

    prompt = stub.system_prompt
    assert "lightly_tsundere" in prompt                      # core_traits
    assert "Relationship subtext" in prompt                   # relationship_to_player.subtext
    assert "Speaking habits" in prompt                        # habits
    assert "Speaking avoid" in prompt                          # avoid
    assert "[praised] Player:" in prompt                       # dialogue_examples few-shot
    assert "emotion.shy" in prompt


def test_companion_llm_prompt_injects_conversation_history() -> None:
    """方案 B 回归：session 历史以对话块形式进入系统提示。"""
    from app.services.companion.session_memory import DialogueTurn

    stub = StubLLMClient(
        {
            "reply_text": "那就接着说。",
            "emotion_id": "emotion.bright",
            "gesture_id": "gesture.cheerful_idle",
            "facial_expression_id": "face.bright_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(
        CompanionDialogueRequest(text="刚说到哪了？", session_id="s1"),
        history=(DialogueTurn(user_text="我们出发吧。", reply_text="当然可以。"),),
    )

    prompt = stub.system_prompt
    assert "Recent conversation" in prompt
    assert "Player: 我们出发吧。" in prompt
    assert "Alice: 当然可以。" in prompt
    assert stub.user_prompt == "刚说到哪了？"


def test_companion_llm_prompt_carries_mood_inertia() -> None:
    """情绪惯性：上一轮的情绪作为「当前心情」注入，且不再要求为变化而换情绪。"""
    from app.services.companion.session_memory import DialogueTurn

    stub = StubLLMClient(
        {
            "reply_text": "嗯，我还在想刚才那件事。",
            "emotion_id": "emotion.thoughtful",
            "gesture_id": "gesture.cheerful_idle",
            "facial_expression_id": "face.gentle_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(
        CompanionDialogueRequest(text="还在想什么？", session_id="s1"),
        history=(
            DialogueTurn(
                user_text="我们出发吧。",
                reply_text="……好。",
                emotion_id="emotion.thoughtful",
            ),
        ),
    )

    prompt = stub.system_prompt
    assert "Your current mood: emotion.thoughtful" in prompt
    assert "keep this mood" in prompt
    # 上一版 Anti-repetition 要求 emotion 也轮换，正是情绪跳变的来源——必须收回
    assert "vary emotion_id" not in prompt


def test_mood_absent_without_recorded_emotion() -> None:
    """旧调用方（或首轮）不传情绪时不注入心情块——行为不变。"""
    from app.services.companion.session_memory import DialogueTurn

    stub = StubLLMClient(
        {
            "reply_text": "那就接着说。",
            "emotion_id": "emotion.bright",
            "gesture_id": "gesture.cheerful_idle",
            "facial_expression_id": "face.bright_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(
        CompanionDialogueRequest(text="刚说到哪了？", session_id="s1"),
        history=(DialogueTurn(user_text="我们出发吧。", reply_text="当然可以。"),),
    )

    assert "Your current mood" not in stub.system_prompt


def test_facts_are_exposed_and_prompt_asks_for_them() -> None:
    """事实通道：prompt 要求顺带抽出玩家陈述的事实，服务暴露 last_facts。"""
    stub = StubLLMClient(
        {
            "reply_text": "小黑啊，记住了。",
            "emotion_id": "emotion.pleased",
            "gesture_id": "gesture.enthusiastic_nod",
            "facial_expression_id": "face.gentle_smile",
            "interruptible": True,
            "facts": ["玩家养了一只叫小黑的猫"],
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="我养了只猫，它叫小黑。"))

    assert service.last_facts == ["玩家养了一只叫小黑的猫"]
    assert "facts: list of 0-3 durable facts" in stub.system_prompt
    # 明确告知「写错会变成永久错误记忆」——这是模型唯一能自己把住的关口。
    assert "permanent false memory" in stub.system_prompt


def test_malformed_facts_are_dropped_without_failing_the_turn() -> None:
    """事实是旁路字段：空白项与超长项直接丢弃，回复照常返回。"""
    stub = StubLLMClient(
        {
            "reply_text": "嗯。",
            "emotion_id": "emotion.pleased",
            "gesture_id": "gesture.enthusiastic_nod",
            "facial_expression_id": "face.gentle_smile",
            "interruptible": True,
            "facts": ["  玩家怕高。  ", "", "长" * 80],
        }
    )
    service = LLMCompanionDialogueService(stub)

    response = service.reply(CompanionDialogueRequest(text="我怕高。"))

    assert response.reply_text == "嗯。"
    assert service.last_facts == ["玩家怕高。"]


def test_old_payloads_without_facts_key_still_work() -> None:
    """向后兼容：不带 facts 键的老模型输出行为不变（空列表）。"""
    stub = StubLLMClient(
        {
            "reply_text": "好。",
            "emotion_id": "emotion.pleased",
            "gesture_id": "gesture.enthusiastic_nod",
            "facial_expression_id": "face.gentle_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="走吧。"))

    assert service.last_facts == []


def test_memory_honesty_rule_present_even_without_history_or_memories() -> None:
    """「不得编造过去」是常驻约束，不随历史/记忆有无开关（修首轮幻视）。

    实测 2026-09-21：会话第一轮（无历史）她说出「上次的烤鱼」，凭空断言
    过去事件——当时该约束被包在 ``if history:`` 里，首轮根本不生效。
    """
    stub = StubLLMClient(
        {
            "reply_text": "嗯？",
            "emotion_id": "emotion.thoughtful",
            "gesture_id": "gesture.think",
            "facial_expression_id": "face.thoughtful",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="在吗？", session_id="s1"))

    prompt = stub.system_prompt
    assert "Memory honesty" in prompt
    assert "NEVER assert any other specific past event" in prompt
    assert "Recent conversation" not in prompt  # 无历史时不注入对话块


def test_memory_honesty_covers_world_state_abilities_and_time() -> None:
    """六修（2026-09-22 实测复盘）：诚实规则从「过去事件」扩到四类。

    实测她还现编了天气（请求无 world_context 也照答「云层压得有点低」）、
    水系魔法（对话链路不引用能力清单）和「才几天不见」（无任何相处时长
    记录）——三类都不在旧的「past event」覆盖里。
    """
    stub = StubLLMClient(
        {
            "reply_text": "嗯？",
            "emotion_id": "emotion.thoughtful",
            "gesture_id": "gesture.think",
            "facial_expression_id": "face.thoughtful",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="在吗？", session_id="s1"))

    prompt = stub.system_prompt
    assert "current world state" in prompt
    assert "your own abilities" in prompt
    assert "how long you have known the player" in prompt


def test_prompt_injects_the_real_ability_catalog() -> None:
    """六修（2026-09-22 实测复盘「水系魔法幻视」）：对话链路注入能力目录。

    真相源是 tactical_policy.abilities——实测她被问「你会什么魔法」时现编
    水系且越编越自洽，因为 prompt 里从来没有过能力清单。
    """
    stub = StubLLMClient(
        {
            "reply_text": "嗯。",
            "emotion_id": "emotion.pleased",
            "gesture_id": "gesture.small_wave",
            "facial_expression_id": "face.gentle_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="你会什么魔法？"))

    prompt = stub.system_prompt
    assert "Your complete and ONLY abilities" in prompt
    for display_name in ("奥术弹", "爆裂魔法", "快速治疗", "强效治疗", "魔法护盾"):
        assert display_name in prompt
    assert "do not invent abilities you were not given" in prompt


def test_prompt_frames_examples_as_placeholders_not_facts() -> None:
    """六修（2026-09-22 实测复盘）：示例块必须框定「世界细节是占位不是事实」。

    few-shot 的天气条曾被逐字复述成「真实天象」——模型把示例当成了数据源。
    """
    stub = StubLLMClient(
        {
            "reply_text": "嗯。",
            "emotion_id": "emotion.pleased",
            "gesture_id": "gesture.small_wave",
            "facial_expression_id": "face.gentle_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="你好。"))

    prompt = stub.system_prompt
    assert "placeholders, NOT facts" in prompt
    assert "never cite anything from an example" in prompt


def test_reply_topics_are_exposed_and_prompt_asks_for_them() -> None:
    """六修：自述主题通道——LLM 顺带返回她本轮谈及的话题，替代规则切词。

    规则提取无分词库，她自己的回复曾切出「主修/厉害/水系本来」这类碎片
    直接落印象层（且新印象立即回注 prompt 污染下一轮）。
    """
    stub = StubLLMClient(
        {
            "reply_text": "护盾我还能撑一会儿，先照顾好你自己。",
            "emotion_id": "emotion.concerned",
            "gesture_id": "gesture.small_wave",
            "facial_expression_id": "face.concerned",
            "interruptible": True,
            "reply_topics": ["护盾"],
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="你还好吗？"))

    assert service.last_reply_topics == ["护盾"]
    assert "reply_topics: list of 1-3 short Chinese topic words" in stub.system_prompt
    # keys 清单同步：模型必须知道这个键存在于「exactly these keys」里
    assert "reply_topics, salient" in stub.system_prompt


def test_old_payloads_without_reply_topics_key_still_work() -> None:
    """向后兼容：不带 reply_topics 键的老模型输出行为不变（空列表）。"""
    stub = StubLLMClient(
        {
            "reply_text": "好。",
            "emotion_id": "emotion.pleased",
            "gesture_id": "gesture.small_wave",
            "facial_expression_id": "face.gentle_smile",
            "interruptible": True,
        }
    )
    service = LLMCompanionDialogueService(stub)

    service.reply(CompanionDialogueRequest(text="走吧。"))

    assert service.last_reply_topics == []


def test_tactical_llm_parser_rejects_extra_fields() -> None:
    parser = LLMCommandParser(
        StubLLMClient(
            {
                "recognized": False,
                "order": None,
                "message": "Unknown command.",
                "unsafe_extra": "must be rejected",
            }
        )
    )

    with pytest.raises(LLMClientError, match="failed validation"):
        parser.parse("做一个不存在的动作")


def test_tactical_llm_parser_marks_its_own_source() -> None:
    parser = LLMCommandParser(
        StubLLMClient(
            {
                "recognized": False,
                "order": None,
                "message": "Unknown command.",
            }
        )
    )

    response = parser.parse("做一个不存在的动作")

    assert response.source == "llm"


class StubStreamingLLMClient:
    """按预定 chunk 列表产出原始文本增量的流式测试替身。"""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        raise AssertionError("stream_reply must not call generate_json")

    def stream_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ):
        yield from self._chunks


_FULL_STREAM_REPLY = (
    '{"reply_text": "好呀，那就走吧。", '
    '"emotion_id": "emotion.bright", '
    '"gesture_id": "gesture.cheerful_idle", '
    '"facial_expression_id": "face.bright_smile", '
    '"interruptible": true, '
    '"topics": ["高塔"], "facts": ["玩家怕高"]}'
)


def _split_mid_word(text: str, parts: int) -> list[str]:
    size = max(1, len(text) // parts)
    return [text[i : i + size] for i in range(0, len(text), size)]


def test_stream_reply_emits_deltas_then_meta() -> None:
    service = LLMCompanionDialogueService(StubStreamingLLMClient(_split_mid_word(_FULL_STREAM_REPLY, 7)))

    events = list(
        service.stream_reply(CompanionDialogueRequest(text="我们出发吧。", session_id="s1"))
    )

    deltas = [e for e in events if e.kind == "delta"]
    metas = [e for e in events if e.kind == "meta"]
    assert "".join(e.text for e in deltas) == "好呀，那就走吧。"
    assert len(metas) == 1
    assert metas[0].response is not None
    assert metas[0].response.reply_text == "好呀，那就走吧。"
    assert metas[0].response.source == "llm"
    assert metas[0].response.session_id == "s1"
    assert all(e.kind != "error" for e in events)
    # 流式路径与非流式一样暴露顺带抽出的主题/事实（供 dialogue_service 落档）。
    assert service.last_facts == ["玩家怕高"]
    assert service.last_topics == ["高塔"]


def test_stream_reply_decodes_escapes_across_chunks() -> None:
    r"""转义序列（\n、\uXXXX）被 chunk 边界切断时也能正确拼出 delta。"""
    chunks = [
        '{"reply_text": "第一行',
        '\\n',
        '第二行 \\u',
        '4e2d',
        '弹"',
        ', "emotion_id": "emotion.bright", "gesture_id": "gesture.cheerful_idle", '
        '"facial_expression_id": "face.bright_smile", "interruptible": true}',
    ]
    service = LLMCompanionDialogueService(StubStreamingLLMClient(chunks))

    events = list(service.stream_reply(CompanionDialogueRequest(text="测试")))

    joined = "".join(e.text for e in events if e.kind == "delta")
    assert joined == "第一行\n第二行 中弹"
    meta = next(e for e in events if e.kind == "meta")
    assert meta.response is not None
    assert meta.response.reply_text == "第一行\n第二行 中弹"


def test_stream_reply_rejects_unknown_ue_id_after_stream() -> None:
    payload = _FULL_STREAM_REPLY.replace("emotion.bright", "emotion.not_registered")
    service = LLMCompanionDialogueService(StubStreamingLLMClient([payload]))

    with pytest.raises(LLMClientError, match="unknown emotion ID"):
        list(service.stream_reply(CompanionDialogueRequest(text="测试")))


def test_stream_reply_rejects_invalid_json() -> None:
    service = LLMCompanionDialogueService(StubStreamingLLMClient(["不是 JSON"]))

    with pytest.raises(LLMClientError, match="not valid JSON"):
        list(service.stream_reply(CompanionDialogueRequest(text="测试")))


# ---------------------------------------------------------------------------
# 两轮查证调用（SDD T069 / FR-036~FR-038）
# ---------------------------------------------------------------------------

_REPLY = {
    "action": "reply",
    "reply_text": "我查过了：护盾就是短期减伤，危险的时候我会给你套上的。",
    "emotion_id": "emotion.pleased",
    "gesture_id": "gesture.cheerful_idle",
    "facial_expression_id": "face.bright_smile",
    "interruptible": True,
    "topics": ["护盾"],
    "salient": False,
}


class TwoRoundStubClient:
    """第一轮索取查证、第二轮据此作答的模型替身；记录每轮 system prompt。"""

    def __init__(self, lookup: dict[str, Any], final: dict[str, Any]) -> None:
        self._lookup = lookup
        self._final = final
        self.prompts: list[str] = []
        self.calls = 0

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2
    ) -> dict[str, Any]:
        self.prompts.append(system_prompt)
        self.calls += 1
        return self._lookup if self.calls == 1 else self._final


def test_first_round_prompt_offers_the_tool_menu() -> None:
    stub = TwoRoundStubClient(_REPLY, _REPLY)

    LLMCompanionDialogueService(stub).reply(CompanionDialogueRequest(text="护盾是什么效果"))

    assert "tool.lore.query" in stub.prompts[0]
    assert "tool.memory.recall" in stub.prompts[0]


def test_direct_reply_stays_single_round() -> None:
    """不索取查证的普通对话仍是老行为：一次调用，v0.1 语义不变。"""
    stub = TwoRoundStubClient(_REPLY, _REPLY)

    response = LLMCompanionDialogueService(stub).reply(
        CompanionDialogueRequest(text="聊点什么吧")
    )

    assert response.source == "llm"
    assert stub.calls == 1


def test_lookup_round_feeds_the_verified_fact_into_the_second_prompt() -> None:
    stub = TwoRoundStubClient(
        {"action": "lookup", "tool": "tool.lore.query", "query": "护盾是什么效果"},
        _REPLY,
    )

    response = LLMCompanionDialogueService(stub).reply(
        CompanionDialogueRequest(text="护盾是什么效果")
    )

    assert response.source == "llm"
    assert stub.calls == 2
    assert "查证结果" in stub.prompts[1]
    assert "护盾" in stub.prompts[1]


def test_lookup_miss_tells_the_model_not_to_invent() -> None:
    """查不到时的回填块必须明确压住编造本能（FR-037）。"""
    stub = TwoRoundStubClient(
        {"action": "lookup", "tool": "tool.lore.query", "query": "这个遗迹是谁建的"},
        _REPLY,
    )

    LLMCompanionDialogueService(stub).reply(
        CompanionDialogueRequest(text="这个遗迹是谁建的")
    )

    assert "没有记载" in stub.prompts[1]
    assert "NOT invent" in stub.prompts[1]


def test_lookup_disabled_by_config_keeps_single_round(monkeypatch) -> None:
    monkeypatch.setenv("AESIR_TOOLS_MAX_ROUNDS", "1")
    stub = TwoRoundStubClient(
        {"action": "lookup", "tool": "tool.lore.query", "query": "护盾"}, _REPLY
    )

    # prompt 里不给工具清单；模型若仍索取查证属于违例输出，按 schema 失败
    # 报错（上层回退候选回复），且绝不出现第二轮
    with pytest.raises(LLMClientError):
        LLMCompanionDialogueService(stub).reply(
            CompanionDialogueRequest(text="护盾是什么效果")
        )

    assert stub.calls == 1
    assert "tool.lore.query" not in stub.prompts[0]


class _TwoRoundStreamStub:
    """流式版两轮替身：第一轮索取查证，第二轮流式作答。"""

    def __init__(self, lookup: dict[str, Any], final: dict[str, Any]) -> None:
        self._rounds = [
            json.dumps(lookup, ensure_ascii=False),
            json.dumps(final, ensure_ascii=False),
        ]
        self.prompts: list[str] = []

    def generate_json(self, *, system_prompt, user_prompt, temperature: float = 0.2):
        raise AssertionError("流式路径不应走非流式调用")

    def stream_completion(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2):
        self.prompts.append(system_prompt)
        raw = self._rounds[min(len(self.prompts) - 1, 1)]
        for i in range(0, len(raw), 24):
            yield raw[i : i + 24]


def test_stream_reply_streams_the_second_round_after_a_lookup() -> None:
    stub = _TwoRoundStreamStub(
        {"action": "lookup", "tool": "tool.lore.query", "query": "护盾是什么效果"},
        _REPLY,
    )
    service = LLMCompanionDialogueService(stub)

    events = list(
        service.stream_reply(CompanionDialogueRequest(text="护盾是什么效果"))
    )

    assert len(stub.prompts) == 2
    deltas = [e.text for e in events if e.kind == "delta"]
    meta = [e for e in events if e.kind == "meta"]
    assert len(meta) == 1
    # 第一轮是查证请求（无 reply_text），玩家看到的全部增量都来自第二轮
    assert "".join(deltas) == _REPLY["reply_text"]
