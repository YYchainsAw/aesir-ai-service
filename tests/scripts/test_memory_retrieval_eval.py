import json
from pathlib import Path

import pytest

from scripts.evaluate_memory_retrieval import compare


def fixture():
    return json.loads(Path('data/evals/memory_retrieval.json').read_text(encoding='utf-8'))


def test_comparison_exposes_semantic_miss_and_keyword_false_recall():
    report = compare(fixture())
    rows = {row['case']: row for row in report['cases']}
    assert rows['old_preference']['budget']['omitted'] == 1
    assert rows['old_preference']['index_read']['omitted'] == 0
    assert rows['synonym_omission']['index_read']['omitted'] == 1
    assert rows['keyword_false_recall']['index_read']['false_recall'] == 1
    assert report['decision'].startswith('retain_budget')
    dead = '10000000-0000-4000-8000-000000000004'
    assert all(dead not in row[s]['ids'] for row in report['cases'] for s in ('budget', 'index_read'))


def test_index_cannot_read_unknown_ids():
    data = fixture()
    data['index'][0]['entry_id'] = '20000000-0000-4000-8000-000000000001'
    with pytest.raises(ValueError, match='unknown entry'):
        compare(data)
