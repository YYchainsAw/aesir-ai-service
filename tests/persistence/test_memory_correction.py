"""Correction authorization also holds in SQL transactions and recovery reads."""
from uuid import UUID

import pytest

from app.persistence.database import Database, reset_database
from app.persistence.auth import use_principal
from app.persistence.uow import use_unit_of_work
from app.schemas.memory import MemoryEntry
from app.scoped.context import NpcScope, RequestScope, use_scope
from app.scoped.idempotency import reset_idempotency_stores
from app.scoped.requests import reset_coordinator
from app.scoped.runtime import reset_runtime
from app.services.memory.store import get_memory_store, reset_memory_stores
from test_auth import access
from test_security_integration import security, payload


def scope(service):
    c = service.context
    return RequestScope(NpcScope('aesir', service.player.player_id, service.player.save_id, 'companion.alice'),
        UUID(c['run_id']), UUID(c['run_id']), UUID(c['service_instance_id']),
        UUID(c['run_binding_id']), UUID(c['memory_epoch']))


def recovery(service):
    result = service.client.get('/v1/scoped/recovery/state', params={
        'save_id': str(service.player.save_id), 'companion_id': 'companion.alice'})
    assert result.status_code == 200, result.text
    return result.json()


def test_correction_commits_once_and_survives_reopened_sql_database(security, monkeypatch):
    shown = MemoryEntry(content='玩家喜欢苹果', importance='critical')
    hidden = MemoryEntry(content='玩家来自港口', importance='low')
    observed = MemoryEntry(content='已经看过路线', source='observation')
    with use_principal(security.player.principal), use_scope(scope(security)):
        get_memory_store('companion.alice').record_facts([shown, hidden, observed])
    monkeypatch.setenv('AESIR_MEMORY_INJECTION_BUDGET', '1')
    monkeypatch.setenv('AESIR_COMPANION_BACKEND', 'llm')
    calls = []
    class Model:
        def generate_json(self, **kwargs):
            calls.append(1)
            return dict(action='reply', reply_text='记下了。', emotion_id='emotion.bright',
                gesture_id='gesture.cheerful_idle', facial_expression_id='face.bright_smile',
                interruptible=True, corrected_fact_ids=[e.entry_id.hex[:8] for e in (shown, hidden, observed)])
    monkeypatch.setattr('app.services.companion.llm_dialogue_service.create_llm_client', lambda: Model())
    body = payload(security, text='苹果那条不对，请作废。', timing=dict(capture_age_ms=0,
        request_age_ms=0, max_snapshot_age_ms=30000, max_request_age_ms=30000))
    response = security.client.post('/v1/scoped/companion/chat', json=body)
    assert response.status_code == 200 and response.json()['source'] == 'llm', response.text
    before = recovery(security)
    entries = {e['entry_id']: e for e in before['memory']['archive']}
    assert entries[str(shown.entry_id)]['superseded_by'] is not None
    assert entries[str(hidden.entry_id)]['superseded_by'] is None
    assert entries[str(observed.entry_id)]['superseded_by'] is None
    assert security.client.post('/v1/scoped/companion/chat', json=body).json() == response.json()
    assert recovery(security) == before
    reset_coordinator()
    reset_idempotency_stores()
    reset_runtime()
    reset_memory_stores()
    reset_database(Database.from_url(f'sqlite:///{security.access.path}'))
    after = recovery(security)
    assert after['service_instance_id'] != before['service_instance_id']
    for field in ('memory', 'relationship', 'memory_epoch', 'state_version', 'save_generation'):
        assert after[field] == before[field]
    operation = security.client.get(f"/v1/scoped/recovery/operations/{body['request_id']}", params={
        'save_id': body['save_id'], 'companion_id': body['companion_id'],
        'run_id': body['run_id'], 'operation': 'chat'})
    assert operation.status_code == 200 and operation.json()['state'] == 'complete', operation.text
    assert 'result' not in operation.json()
    assert security.client.post('/v1/scoped/companion/chat', json=body).status_code == 409
    assert calls == [1]


def test_rolled_back_correction_does_not_leak_into_recovery(security):
    entry = MemoryEntry(content='玩家喜欢苹果')
    active = scope(security)
    with use_principal(security.player.principal), use_scope(active):
        get_memory_store('companion.alice').record_fact(entry)
        before = recovery(security)
        with pytest.raises(RuntimeError, match='abort'):
            with use_unit_of_work(active.npc):
                assert get_memory_store('companion.alice').mark_superseded_by_entry_id(
                    entry.entry_id.hex[:8], allowed_entry_ids=frozenset({entry.entry_id}),
                    allowed_sources=frozenset({'player_statement'})) == 1
                raise RuntimeError('abort')
    assert recovery(security) == before
