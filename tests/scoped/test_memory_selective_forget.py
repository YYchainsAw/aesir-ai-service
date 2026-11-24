"""Known unrelated data survives; replies depending on forgotten data do not."""
from uuid import uuid4

from app.schemas.memory import MemoryEntry, MemorySnapshot
from app.scoped.context import use_scope
from app.scoped.trace import request_trace
from app.scoped.storage import read_memory_document
from app.services.companion.session_memory import get_session_memory
from app.services.memory.store import get_memory_store, invalidate_scope
from test_scoped_api import h


def record(active, text, topic, *, entry=None, injected=()):
    rid = str(uuid4())
    with use_scope(active), request_trace(active, 'chat', rid):
        store = get_memory_store('companion.alice')
        if entry:
            store.record_fact(entry)
        store.record_mention([topic])
        get_session_memory(10).record(str(active.session_id), text, '收到', companion_id='companion.alice',
                                     entry_ids=tuple([*(str(value) for value in injected),
                                                      *([str(entry.entry_id)] if entry else [])]))
    return rid


def test_selective_forget_keeps_unrelated_earlier_turn_and_other_run(h):
    context = h.bind()
    active = h.scope(context)
    other = MemoryEntry(content='玩家住在港口')
    chosen = MemoryEntry(content='玩家喜欢香蕉')
    record(active, '我住在港口', '港口', entry=other)
    record(active, '我喜欢香蕉', '香蕉', entry=chosen)
    dependent = record(active, '你再重复一遍', '水果', injected=(chosen.entry_id,))
    context = h.bind()  # A distinct run/session without the old reply context.
    independent = h.scope(context)
    record(independent, '去钓鱼吧', '钓鱼')
    invalidate_scope(independent.npc)  # Attribution survives a JSON reload.
    response = h.client.post('/v1/scoped/console/memory/forget', json=h.payload(context, entry_ids=[str(chosen.entry_id)]))
    assert response.status_code == 200, response.text
    assert response.json()['cleared_sessions'] == 1
    fresh = h.scope(h.context())
    _, snapshot = read_memory_document(fresh.npc)
    assert [entry.entry_id for entry in snapshot.archive] == [other.entry_id]
    assert {item.topic for item in snapshot.impressions} == {'港口', '钓鱼'}
    assert dependent not in str(snapshot.to_document())
    with use_scope(fresh):
        assert [turn.user_text for turn in get_session_memory(10).history(str(fresh.session_id), 'companion.alice')] == ['去钓鱼吧']
    # History reads are scoped, but do not pretend an old run is reusable for writes.
    with use_scope(active):
        assert [turn.user_text for turn in get_session_memory(10).history(str(active.session_id), 'companion.alice')] == ['我住在港口']


def test_duplicate_fact_all_associated_topics_are_forgotten(h):
    context = h.bind()
    active = h.scope(context)
    first = MemoryEntry(content='玩家喜欢香蕉')
    record(active, '我喜欢香蕉', '水果', entry=first)
    record(active, '我喜欢香蕉', '早餐', entry=MemoryEntry(content=first.content))
    response = h.client.post('/v1/scoped/console/memory/forget', json=h.payload(context, entry_ids=[str(first.entry_id)]))
    assert response.status_code == 200, response.text
    _, snapshot = read_memory_document(active.npc)
    assert not snapshot.archive and not snapshot.impressions


def test_forget_follows_reply_dependencies_after_original_turn_leaves_window(h):
    context = h.bind()
    active = h.scope(context)
    chosen = MemoryEntry(content='玩家喜欢香蕉')
    record(active, '我喜欢香蕉', '香蕉', entry=chosen)
    for _ in range(12):
        record(active, '然后呢', '故事')
    with use_scope(active):
        history = get_session_memory(10).history(str(active.session_id), 'companion.alice')
        assert len(history) == 10 and history[0].user_text == '然后呢'
        assert all(str(chosen.entry_id) in turn.entry_ids for turn in history)
    result = h.client.post('/v1/scoped/console/memory/forget', json=h.payload(context, entry_ids=[str(chosen.entry_id)]))
    assert result.status_code == 200, result.text
    with use_scope(active):
        assert not get_session_memory(10).history(str(active.session_id), 'companion.alice')


def test_truncated_dependency_ledger_cannot_retain_a_potentially_derived_fact():
    from app.services.memory.provenance import merge_tags
    from app.services.memory.attribution import forget_plan
    from types import SimpleNamespace
    chosen = MemoryEntry(content='玩家喜欢香蕉')
    derived = MemoryEntry(content='玩家喜爱香蕉', tags=merge_tags([
        *(f'trace.depends_on_request_id={i}' for i in range(40))]))
    assert 'trace.attribution_truncated=true' in derived.tags
    snapshot = MemorySnapshot(archive=[chosen, derived])
    removed, _ = forget_plan(snapshot, {chosen.entry_id},
                            SimpleNamespace(affected_requests=lambda *args:set()), None)
    assert str(derived.entry_id) in removed


def test_reply_impression_dependency_survives_disabled_session_history(h, monkeypatch):
    from app.schemas.companion_dialogue import CompanionDialogueRequest, CompanionDialogueResponse
    from app.services.companion.dialogue_service import _record_turn
    context = h.bind()
    active = h.scope(context)
    chosen = MemoryEntry(content='玩家喜欢香蕉')
    monkeypatch.setenv('AESIR_DIALOGUE_HISTORY_TURNS', '0')
    with use_scope(active), request_trace(active, 'chat', str(uuid4())):
        get_memory_store('companion.alice').record_fact(chosen)
    with use_scope(active), request_trace(active, 'chat', str(uuid4())):
        _record_turn(CompanionDialogueRequest(text='你好',session_id=str(active.session_id)),
            CompanionDialogueResponse(companion_id='companion.alice',reply_text='香蕉不错。',emotion_id='emotion.bright',
                gesture_id='gesture.cheerful_idle',facial_expression_id='face.bright_smile',interruptible=True,source='llm'),
            topics=[],facts=[],salient=False,reply_topics=['水果'],game_id='aesir',
            injected_entry_ids=(str(chosen.entry_id),))
    result = h.client.post('/v1/scoped/console/memory/forget', json=h.payload(context, entry_ids=[str(chosen.entry_id)]))
    assert result.status_code == 200, result.text
    _, snapshot = read_memory_document(active.npc)
    assert not snapshot.impressions


def test_lineage_is_internal_bounded_and_unknown_overflow_is_conservative():
    snapshot = MemorySnapshot.from_document({'_memory_links': {'钓鱼':['r:a','e:b']}})
    assert '_memory_links' not in snapshot.model_dump(mode='json')
    assert snapshot.model_copy(deep=True)._memory_links == snapshot._memory_links
    import pytest
    with pytest.raises(ValueError):
        MemorySnapshot.from_document({'_memory_links': {'钓鱼':['r:x']*129}})
