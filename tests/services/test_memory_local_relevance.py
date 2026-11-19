"""Query-aware recall must not grant relevance from importance or stale facts."""
from app.schemas.memory import MemoryEntry, MemorySnapshot
from app.services.memory.retrieval import retrieve


class Store:
    def __init__(self, entries):
        self.value = MemorySnapshot(archive=entries)
    def snapshot(self):
        return self.value


def test_old_relevant_fact_outranks_recent_critical_unrelated_and_stale_entry():
    wanted = MemoryEntry(content='玩家的家乡是港口小镇', importance='low')
    stale = MemoryEntry(content='玩家家乡是山城', superseded_by=wanted.entry_id, importance='critical')
    noise = MemoryEntry(content='玩家答应带地图', importance='critical')
    store = Store([noise, stale, wanted])
    assert retrieve(store, query='我是哪里人', budget=1) == [wanted]
    assert retrieve(store, budget=1) == [noise]
    assert retrieve(store, query='下次考试是哪天') == []


def test_shared_entity_is_not_evidence_for_unknown_price_or_year():
    store = Store([MemoryEntry(content='玩家对花生过敏'), MemoryEntry(content='玩家家乡是港口小镇')])
    assert retrieve(store, query='不能吃哪种坚果') == [store.value.archive[0]]
    assert retrieve(store, query='花生多少钱') == []
    assert retrieve(store, query='港口哪一年建的') == []


def test_empty_query_does_not_reintroduce_irrelevant_entries():
    assert retrieve(Store([MemoryEntry(content='玩家喜欢香蕉')]), query='') == []
    assert retrieve(Store([]), query='家乡') == []


def test_implicit_personal_question_preserves_original_budget_fallback():
    entry = MemoryEntry(content='玩家的职业是木匠')
    store = Store([entry])
    assert retrieve(store, query='我是靠哪门手艺谋生的？') == [entry]
    assert retrieve(store, query='我住的地方是哪一年建成的？') == []
