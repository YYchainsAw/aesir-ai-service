from uuid import uuid4

from app.schemas.memory import MemoryEntry
from app.scoped.context import use_scope
from app.scoped.identity import Principal, get_principal
from app.services.memory.store import get_memory_store
from test_scoped_api import h


def entries(h, context):
    query={key:value for key,value in h.payload(context).items() if key not in ('protocol_version','request_id')}
    return h.client.get('/v1/scoped/console/memory/entries', params=query)


def test_entry_forget_rotates_epoch_replays_once_and_preserves_other_entries(h):
    context=h.bind()
    chosen,other=MemoryEntry(content='玩家喜欢香蕉'),MemoryEntry(content='玩家住在港口')
    with use_scope(h.scope(context)):
        store=get_memory_store('companion.alice')
        store.record_facts([chosen,other])
        store.record_mention(['香蕉'])
    assert {row['entry_id'] for row in entries(h,context).json()['entries']} == {str(chosen.entry_id),str(other.entry_id)}
    body=h.payload(context,entry_ids=[str(chosen.entry_id)])
    first=h.client.post('/v1/scoped/console/memory/forget',json=body)
    assert first.status_code==200,first.text
    assert first.json()['memory_epoch']!=context['memory_epoch']
    assert first.json()['forgotten_entry_ids']==[str(chosen.entry_id)]
    assert h.client.post('/v1/scoped/console/memory/forget',json=body).json()==first.json()
    stale=h.client.post('/v1/scoped/companion/chat',json=h.chat(context))
    assert stale.status_code==409 and stale.json()['detail']['code']=='MEMORY_EPOCH_STALE'
    fresh=h.context()
    rows=entries(h,fresh).json()['entries']
    assert [row['entry_id'] for row in rows]==[str(other.entry_id)]
    with use_scope(h.scope(fresh)):
        assert not get_memory_store('companion.alice').snapshot().impressions


def test_forget_unknown_mixed_targets_has_no_partial_effect(h):
    context=h.bind()
    entry=MemoryEntry(content='玩家喜欢香蕉')
    with use_scope(h.scope(context)):
        get_memory_store('companion.alice').record_fact(entry)
    response=h.client.post('/v1/scoped/console/memory/forget',json=h.payload(context,
        entry_ids=[str(entry.entry_id),str(uuid4())]))
    assert response.status_code==404,response.text
    assert h.context()['memory_epoch']==context['memory_epoch']
    assert len(entries(h,context).json()['entries'])==1


def test_entry_query_and_forget_require_separate_permissions(h):
    context=h.bind()
    h.client.app.dependency_overrides[get_principal]=lambda:Principal(
        h.principal.player_id,h.principal.save_ids,permissions=frozenset({'npc:use'}))
    assert entries(h,context).status_code==403
    response=h.client.post('/v1/scoped/console/memory/forget',json=h.payload(context,entry_ids=[str(uuid4())]))
    assert response.status_code==403


def test_cross_save_and_duplicate_entry_ids_are_rejected(h):
    context=h.bind()
    body=h.payload(context,save_id=str(uuid4()),entry_ids=[str(uuid4())])
    assert h.client.post('/v1/scoped/console/memory/forget',json=body).status_code==403
    target=str(uuid4())
    body=h.payload(context,entry_ids=[target,target])
    assert h.client.post('/v1/scoped/console/memory/forget',json=body).status_code==422
