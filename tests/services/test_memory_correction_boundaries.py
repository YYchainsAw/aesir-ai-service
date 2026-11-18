"""LLM correction candidates may only affect the shown player-owned facts."""
from uuid import UUID

import pytest

from app.schemas.memory import MemoryEntry
from app.services.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    store = MemoryStore('companion.alice', root=str(tmp_path))
    store.load()
    return store


@pytest.mark.parametrize('candidate', ['a', 'abcdef0', 'not-hex!', 'abcdef001', '[ID:a]'])
def test_incomplete_or_malformed_ids_never_invalidate_facts(store, candidate):
    entry = MemoryEntry(entry_id=UUID('abcdef00-0000-4000-8000-000000000001'), content='玩家喜欢苹果')
    store.record_fact(entry)
    assert store.mark_superseded_by_entry_id(candidate) == 0
    assert store.snapshot().archive[0].superseded_by is None


def test_short_collision_is_rejected_and_full_id_can_disambiguate(store):
    entries = [MemoryEntry(entry_id=UUID(value), content=text) for value,text in [
        ('abcdef00-0000-4000-8000-000000000001','玩家喜欢苹果'),
        ('abcdef00-0000-4000-8000-000000000002','玩家喜欢橙子')]]
    for entry in entries:
        store.record_fact(entry)
    assert store.mark_superseded_by_entry_id('abcdef00') == 0
    assert all(entry.superseded_by is None for entry in store.snapshot().archive)
    assert store.mark_superseded_by_entry_id(str(entries[0].entry_id)) == 1
    assert sum(entry.superseded_by is not None for entry in store.snapshot().archive) == 1


def test_hidden_fact_and_non_player_source_cannot_be_corrected(store):
    shown = MemoryEntry(content='玩家喜欢苹果')
    hidden = MemoryEntry(content='玩家来自港口')
    observed = MemoryEntry(content='已经完成遗迹探索', source='shared_experience')
    for entry in (shown, hidden, observed):
        store.record_fact(entry)
    allowed = frozenset((shown.entry_id, observed.entry_id))
    sources = frozenset(('player_statement','promise'))
    for entry in (hidden, observed):
        assert store.mark_superseded_by_entry_id(entry.entry_id.hex[:8],
            allowed_entry_ids=allowed, allowed_sources=sources) == 0
    assert store.mark_superseded_by_entry_id(shown.entry_id.hex[:8],
        allowed_entry_ids=allowed, allowed_sources=sources) == 1


def test_dialogue_commit_only_uses_actual_injected_correction_targets(monkeypatch):
    from app.schemas.companion_dialogue import CompanionDialogueRequest, CompanionDialogueResponse
    from app.services.companion import dialogue_service as dialogue
    shown = MemoryEntry(content='玩家喜欢苹果')
    hidden = MemoryEntry(content='玩家来自港口')
    captured = {}

    class Generated:
        last_corrected_fact_ids = [shown.entry_id.hex[:8], hidden.entry_id.hex[:8]]
        last_style_violations = []

    monkeypatch.setattr(dialogue, '_record_turn', lambda *args, **kwargs: captured.update(kwargs) or 0)
    response = CompanionDialogueResponse(companion_id='companion.alice', source='llm', reply_text='记下了。',
        emotion_id='emotion.bright', gesture_id='gesture.cheerful_idle', facial_expression_id='face.bright_smile', interruptible=True)
    profile = dialogue.get_registered_profile('companion.alice')
    dialogue._complete_reply(CompanionDialogueRequest(text='改一下'), response,
        profile=profile, stage='distant', memories=[shown], impressions=[], game_id='aesir', service=Generated())
    assert captured['correction_targets'] == frozenset((shown.entry_id,))
