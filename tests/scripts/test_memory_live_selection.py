import pytest
from app.schemas.memory import MemoryEntry
from scripts.evaluate_memory_retrieval_live import select_entries


@pytest.mark.parametrize('candidate',[{'ids':['unknown']},{'ids':['a','a']},{'ids':[1]},{'ids':['a','b','c']},{}])
def test_model_selection_cannot_expand_scope_or_budget(candidate):
    with pytest.raises(ValueError):
        select_entries(candidate,{'a':MemoryEntry(content='香蕉')},2)


def test_valid_selection_reads_only_whitelisted_entries():
    entry=MemoryEntry(content='香蕉')
    assert select_entries({'ids':['a']},{'a':entry},2)==[entry]
    assert select_entries({'ids':[]},{'a':entry},2)==[]
