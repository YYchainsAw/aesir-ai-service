import json
import os
from pathlib import Path

import pytest

from app.schemas.memory import MemoryEntry
from app.scoped.context import use_scope
from app.services.memory.store import get_memory_store
from test_scoped_api import h


@pytest.mark.parametrize('extra_target', ['world', 'other'])
@pytest.mark.parametrize('query,applied', [('苹果那条不对，请作废。', 1), ('我喜欢在雨天钓鱼', 0)])
def test_llm_cannot_correct_hidden_world_or_other_companion_memory(h, monkeypatch, extra_target, query, applied):
    context = h.bind()
    shown = MemoryEntry(content='玩家喜欢苹果', importance='critical')
    hidden = MemoryEntry(content='玩家来自港口', importance='low')
    world = MemoryEntry(content='遗迹已探索', source='shared_experience')
    other = MemoryEntry(content='玩家喜欢橙子')
    with use_scope(h.scope(context)):
        store = get_memory_store('companion.alice')
        for entry in (shown, hidden, world):
            store.record_fact(entry)
    other_context = h.context(npc='companion.bruno')
    with use_scope(h.scope(other_context)):
        get_memory_store('companion.bruno').record_fact(other)
    monkeypatch.setenv('AESIR_MEMORY_INJECTION_BUDGET','1')
    monkeypatch.setenv('AESIR_COMPANION_BACKEND','llm')
    class Model:
        def generate_json(self, **kwargs):
            return dict(action='reply', reply_text='记下了。', emotion_id='emotion.bright',
                gesture_id='gesture.cheerful_idle', facial_expression_id='face.bright_smile',
                interruptible=True, topics=[], facts=[], salient=False, reply_topics=[],
                corrected_fact_ids=[entry.entry_id.hex[:8] for entry in
                                    (shown, hidden, world if extra_target == 'world' else other)])
    monkeypatch.setattr('app.services.companion.llm_dialogue_service.create_llm_client', lambda: Model())
    body = h.chat(context)
    body['text'] = query
    response = h.client.post('/v1/scoped/companion/chat', json=body)
    assert response.status_code == 200 and response.json()['source'] == 'llm', response.text
    with use_scope(h.scope(context)):
        entries = {entry.entry_id:entry for entry in store.snapshot().archive}
        assert (entries[shown.entry_id].superseded_by is not None) == bool(applied)
        assert entries[hidden.entry_id].superseded_by is None
        assert entries[world.entry_id].superseded_by is None
    with use_scope(h.scope(other_context)):
        assert get_memory_store('companion.bruno').snapshot().archive[0].superseded_by is None
    rows = [json.loads(line) for path in Path(os.environ['AESIR_DIALOGUE_SIGNALS_DIR']).rglob('*.jsonl')
            for line in path.read_text(encoding='utf-8').splitlines()]
    row = next(row for row in rows if row.get('request_id') == body['request_id'])
    assert row['memory_corrections'] == dict(proposed=3, applied=applied, rejected=3-applied)
    assert h.client.post('/v1/scoped/companion/chat', json=body).json() == response.json()
