import pytest
from uuid import uuid4

from app.persistence.auth import use_principal
from app.persistence.database import read_document, Database, reset_database
from app.persistence.uow import use_unit_of_work
from app.schemas.memory import MemoryEntry
from app.scoped.context import use_scope
from app.scoped.storage import forget_memory, read_memory_document
from app.scoped.trace import request_trace
from app.services.companion.session_memory import get_session_memory, SessionMemoryStore
from app.services.memory.store import get_memory_store
from test_auth import access
from test_security_integration import security, payload
from test_memory_correction import scope, recovery


def populate(security, monkeypatch):
    import app.services.companion.session_memory as sm
    monkeypatch.setattr(sm, '_store', SessionMemoryStore(10))
    active = scope(security)
    records = [MemoryEntry(content='玩家住在港口'), MemoryEntry(content='玩家喜欢香蕉')]
    with use_principal(security.player.principal), use_scope(active):
        for entry, topic in zip(records, ['港口','香蕉']):
            with request_trace(active, 'chat', str(uuid4())):
                store = get_memory_store('companion.alice')
                store.record_fact(entry)
                store.record_mention([topic])
                get_session_memory(10).record(str(active.session_id), entry.content, '收到',
                    companion_id='companion.alice', entry_ids=(str(entry.entry_id),))
    return active, records


def test_sql_rollback_keeps_links_epoch_and_sessions_then_committed_forget_is_durable(security, monkeypatch):
    active, (kept, chosen) = populate(security, monkeypatch)
    with use_principal(security.player.principal), use_scope(active):
        before = read_document('memory', active.npc.key)
        assert '_memory_links' in before
        assert '_memory_links' not in recovery(security)['memory']
        with pytest.raises(RuntimeError, match='abort'):
            with use_unit_of_work(active.npc):
                forget_memory(active.npc, active.memory_epoch, [chosen.entry_id])
                assert len(get_session_memory(10).history(str(active.session_id),'companion.alice')) == 2
                raise RuntimeError('abort')
        assert read_document('memory', active.npc.key) == before
        assert len(get_session_memory(10).history(str(active.session_id),'companion.alice')) == 2
    result = security.client.post('/v1/scoped/console/memory/forget', json=payload(security, entry_ids=[str(chosen.entry_id)]))
    assert result.status_code == 200, result.text
    with use_scope(active):
        assert [turn.user_text for turn in get_session_memory(10).history(str(active.session_id),'companion.alice')] == [kept.content]
    reset_database(Database.from_url(f'sqlite:///{security.access.path}'))
    _, snapshot = read_memory_document(active.npc)
    assert [entry.entry_id for entry in snapshot.archive] == [kept.entry_id]
    assert [item.topic for item in snapshot.impressions] == ['港口']
    assert snapshot._memory_links['港口']
