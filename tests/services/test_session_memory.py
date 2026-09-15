"""方案 B：会话短期记忆的单元与集成测试。"""

from app.services.companion.session_memory import SessionMemoryStore


def test_record_and_history_roundtrip() -> None:
    store = SessionMemoryStore(max_turns=3)
    store.record("s1", "你好", "我在呢。")
    store.record("s1", "聊点什么", "好呀。")

    history = store.history("s1")
    assert [t.user_text for t in history] == ["你好", "聊点什么"]
    assert [t.reply_text for t in history] == ["我在呢。", "好呀。"]


def test_history_window_evicts_oldest() -> None:
    store = SessionMemoryStore(max_turns=2)
    for i in range(4):
        store.record("s1", f"u{i}", f"r{i}")

    history = store.history("s1")
    assert [t.user_text for t in history] == ["u2", "u3"]


def test_sessions_are_isolated() -> None:
    store = SessionMemoryStore(max_turns=3)
    store.record("s1", "你好", "我在呢。")
    assert store.history("s2") == ()


def test_zero_max_turns_disables_memory() -> None:
    store = SessionMemoryStore(max_turns=0)
    store.record("s1", "你好", "我在呢。")
    assert store.history("s1") == ()


def test_create_dialogue_reply_records_session_turns(monkeypatch) -> None:
    # 集成：mock 后端 + session_id → 回复落记忆窗口；无 session_id 不记录。
    from app.services.companion import dialogue_service as ds
    from app.services.companion.session_memory import get_session_memory
    from app.schemas.companion_dialogue import CompanionDialogueRequest

    store = get_session_memory(10)
    response = ds.create_dialogue_reply(
        CompanionDialogueRequest(text="今天过得怎么样？", session_id="it-1")
    )
    assert response.session_id == "it-1"

    history = store.history("it-1")
    assert len(history) == 1
    assert history[0].user_text == "今天过得怎么样？"
    assert history[0].reply_text == response.reply_text

    ds.create_dialogue_reply(CompanionDialogueRequest(text="天气不错"))
    assert len(store.history("it-1")) == 1  # 无 session_id 的请求不写入任何会话
