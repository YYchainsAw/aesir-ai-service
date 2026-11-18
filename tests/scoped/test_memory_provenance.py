from app.schemas.memory import MemoryEntry
from app.scoped.context import use_scope
from app.services.memory.store import get_memory_store
from test_scoped_api import h


def test_player_fact_retains_logical_request_and_scope(h):
    context=h.bind()
    body=h.chat(context)
    body['text']='请记住，我最喜欢的水果是香蕉。'
    response=h.client.post('/v1/scoped/companion/chat',json=body)
    assert response.status_code==200,response.text
    with use_scope(h.scope(context)):
        rows=get_memory_store('companion.alice').snapshot().archive
    assert rows
    for row in rows:
        assert f"trace.request_id={body['request_id']}" in row.tags
        assert f"trace.save_id={body['save_id']}" in row.tags
        assert f"trace.memory_epoch={body['memory_epoch']}" in row.tags
        assert 'trace.origin=verbatim_player' in row.tags


def test_world_event_summary_preserves_event_identity_and_reported_time(h):
    context=h.bind()
    body=h.event(context)
    body['event'].update(event_type='gift_given',details={'item_name':'月光花'})
    response=h.client.post('/v1/scoped/world/events',json=body)
    assert response.status_code==200,response.text
    with use_scope(h.scope(context)):
        rows=get_memory_store('companion.alice').snapshot().summaries
    assert len(rows)==1
    assert f"trace.event_id={body['event']['event_id']}" in rows[0].tags
    assert f"trace.request_id={body['request_id']}" in rows[0].tags
    assert f"trace.occurred_at={body['event']['occurred_at']}" in rows[0].tags
    assert h.client.post('/v1/scoped/world/events',json=body).status_code==200
    with use_scope(h.scope(context)):
        assert len(get_memory_store('companion.alice').snapshot().summaries)==1


def test_duplicate_fact_merges_source_references_without_reidentifying_entry(h):
    context=h.bind()
    entry=MemoryEntry(content='玩家喜欢香蕉',tags=['trace.request_id=first'])
    other=MemoryEntry(content='玩家喜欢香蕉',tags=['trace.request_id=second'])
    with use_scope(h.scope(context)):
        store=get_memory_store('companion.alice')
        store.record_fact(entry)
        store.record_fact(other)
        rows=store.snapshot().archive
    assert len(rows)==1 and rows[0].entry_id==entry.entry_id
    assert {'trace.request_id=first','trace.request_id=second'} <= set(rows[0].tags)


def test_repeated_trace_references_remain_bounded_and_keep_original_identity():
    from app.services.memory.provenance import merge_tags
    tags=merge_tags(['fact',*(f'trace.request_id={i}' for i in range(100))])
    assert len(tags)==33
    assert 'trace.request_id=0' in tags and 'trace.request_id=99' in tags
    assert merge_tags(tags,tags)==tags
