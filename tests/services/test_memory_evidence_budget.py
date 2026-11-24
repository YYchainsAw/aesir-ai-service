"""Evidence periods and rendered context bounds, independent of provider output."""
import pytest
from app.schemas.memory import MemoryEntry
from app.services.memory.retrieval import retrieve, format_memory_block
from test_memory_local_relevance import Store


@pytest.mark.parametrize('query', ['我小时候住的那座镇子是哪儿？', '我的童年在哪度过？',
    '我儿时住在哪里？', 'Where did I grow up?', 'Where did I live as a child?',
    'What was my childhood home?'])
def test_hometown_cannot_establish_childhood_even_through_fallback(query):
    store = Store([MemoryEntry(content='玩家的家乡是港口小镇',importance='critical')])
    assert retrieve(store, query=query) == []


@pytest.mark.parametrize('query', ['我小时候住在哪里？','Where did I live as a child?','Where did I grow up?'])
def test_explicit_period_can_be_recalled_and_superseded_evidence_stays_excluded(query):
    current = MemoryEntry(content='玩家小时候住在山城',importance='normal')
    old = MemoryEntry(content='玩家童年住在港口',superseded_by=current.entry_id,importance='critical')
    assert retrieve(Store([old, current]),query=query) == [current]


def test_character_boundary_counts_rendered_ids_sources_and_actual_display_name():
    first = MemoryEntry(content='玩家住在港口',importance='critical')
    second = MemoryEntry(content='玩家喜欢香蕉')
    name = '名称较长的同伴'
    limit = len(format_memory_block([first],name))
    store = Store([first,second])
    result = retrieve(store,char_budget=limit,display_name=name)
    assert result == [first]
    assert len(format_memory_block(result,name)) == limit
    assert not retrieve(Store([first]),char_budget=limit-1,display_name=name)


def test_oversize_fact_is_skipped_whole_without_losing_trailing_negation():
    long = MemoryEntry(content='旅行记录'*300+'，玩家没有到过港口。',importance='critical')
    short = MemoryEntry(content='玩家喜欢香蕉')
    limit = len(format_memory_block([short]))
    store = Store([long,short])
    assert retrieve(store,char_budget=limit) == [short]
    assert store.value.archive[0].content == long.content
    assert len(store.value.archive) == 2


def test_zero_character_budget_does_not_read_storage():
    class Unreadable:
        def snapshot(self):
            raise AssertionError('disabled injection must not read')
    assert retrieve(Unreadable(),char_budget=0) == []


def test_count_limit_and_character_limit_both_apply(monkeypatch):
    monkeypatch.setenv('AESIR_MEMORY_INJECTION_CHAR_BUDGET','500')
    entries = [MemoryEntry(content=f'记录{i}：'+'出发前的约定。'*50) for i in range(12)]
    selected = retrieve(Store(entries),budget=12)
    assert len(selected) < 12
    assert len(format_memory_block(selected)) <= 500
    assert len(retrieve(Store(entries),budget=1,char_budget=6000)) == 1
