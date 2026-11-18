from app.persistence.database import Database, reset_database
from app.schemas.memory import MemoryEntry
from app.scoped.context import use_scope
from app.persistence.auth import use_principal
from app.scoped.runtime import reset_runtime
from app.services.memory.store import get_memory_store
from test_auth import access
from test_security_integration import security, payload
from test_security_integration import delayed_generation
from test_memory_correction import scope,recovery


def test_sql_forget_is_durable_idempotent_and_preserves_relationship(security):
    entry=MemoryEntry(content='玩家喜欢香蕉')
    with use_principal(security.player.principal),use_scope(scope(security)):
        get_memory_store('companion.alice').record_fact(entry)
    before=recovery(security)
    body=payload(security,entry_ids=[str(entry.entry_id)])
    response=security.client.post('/v1/scoped/console/memory/forget',json=body)
    assert response.status_code==200,response.text
    changed=recovery(security)
    assert changed['memory_epoch']!=before['memory_epoch']
    assert changed['relationship']==before['relationship']
    assert not changed['memory']['archive']
    assert security.client.post('/v1/scoped/console/memory/forget',json=body).json()==response.json()
    assert recovery(security)==changed
    reset_runtime()
    reset_database(Database.from_url(f'sqlite:///{security.access.path}'))
    assert recovery(security)['memory']==changed['memory']
    assert recovery(security)['memory_epoch']==changed['memory_epoch']


def test_sql_forget_commit_failure_does_not_delete_any_entries(security,monkeypatch):
    from app.persistence.uow import UnitOfWork
    from app.scoped.errors import ScopeError
    entry=MemoryEntry(content='玩家喜欢香蕉')
    with use_principal(security.player.principal),use_scope(scope(security)):
        get_memory_store('companion.alice').record_fact(entry)
    before=recovery(security)
    original=UnitOfWork.commit
    def fail(self):
        if any(key[0]=='memory' for key in self.changes):
            raise ScopeError(503,'STATE_UNAVAILABLE','synthetic write failure')
        return original(self)
    monkeypatch.setattr(UnitOfWork,'commit',fail)
    response=security.client.post('/v1/scoped/console/memory/forget',json=payload(security,entry_ids=[str(entry.entry_id)]))
    assert response.status_code==503,response.text
    assert recovery(security)==before


def test_old_offline_fact_does_not_restore_forgotten_memory(security):
    from test_sync import fact,batch,post
    original=fact(security)
    first=post(security,batch(security,[original])).json()['acknowledgements'][0]
    before=recovery(security)
    chosen=before['memory']['summaries'][0]['entry_id']
    unseen=fact(security)
    forgotten=security.client.post('/v1/scoped/console/memory/forget',json=payload(security,entry_ids=[chosen]))
    assert forgotten.status_code==200,forgotten.text
    after=recovery(security)
    duplicate=post(security,batch(security,[original])).json()['acknowledgements'][0]
    assert duplicate['memory_status']==first['memory_status']
    assert not recovery(security)['memory']['summaries']
    new_ack=post(security,batch(security,[unseen])).json()['acknowledgements'][0]
    assert new_ack['memory_status']=='skipped_reset'
    assert new_ack['relationship_status']!='skipped_reset'
    assert recovery(security)['memory']==after['memory']


def test_inflight_generated_reply_cannot_commit_after_forget(security,delayed_generation):
    from concurrent.futures import ThreadPoolExecutor
    entered,release,calls=delayed_generation
    entry=MemoryEntry(content='玩家喜欢香蕉')
    with use_principal(security.player.principal),use_scope(scope(security)):
        get_memory_store('companion.alice').record_fact(entry)
    body=payload(security,text='请聊聊水果',timing=dict(capture_age_ms=0,request_age_ms=0,
        max_snapshot_age_ms=30000,max_request_age_ms=30000))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(security.client.post,'/v1/scoped/companion/chat',json=body)
        try:
            assert entered.wait(5)
            forgotten=security.client.post('/v1/scoped/console/memory/forget',
                json=payload(security,entry_ids=[str(entry.entry_id)]))
            assert forgotten.status_code==200,forgotten.text
        finally:
            release.set()
        response=future.result(5)
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='MEMORY_EPOCH_STALE'
    assert not recovery(security)['memory']['archive']
