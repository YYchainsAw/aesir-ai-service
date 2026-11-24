import json
from pathlib import Path
import pytest
from scripts.evaluate_memory_relevance import compare, answer_correct, rescore


def fixture():
    return json.loads(Path('data/evals/memory_relevance.json').read_text(encoding='utf-8'))


def test_expanded_fixture_preserves_explicit_semantic_limit_and_cost_distinction():
    data = fixture()
    result = compare(data)
    assert len(result['cases']) == 40
    assert result['totals']['local']['exact'] > result['totals']['budget']['exact']
    assert result['totals']['local']['recall'] >= result['totals']['budget']['recall']
    assert result['totals']['local']['payload_chars'] < result['totals']['budget']['payload_chars']
    assert 'prompt_tokens' not in str(result)
    assert all(str(data['entries'][-1]['entry_id']) not in row['local']['ids'] for row in result['cases'])


def test_untrusted_expectations_cannot_reference_missing_or_superseded_ids():
    data = fixture()
    data['cases'][0]['expected'] = [data['entries'][-1]['entry_id']]
    with pytest.raises(ValueError, match='Invalid expected'):
        compare(data)


def test_childhood_is_not_established_by_hometown_and_rescore_uses_saved_answers():
    data = fixture()
    case = next(case for case in data['cases'] if case['name']=='implicit_home')
    assert case['expected'] == [] and case['answer_terms'] == []
    assert not answer_correct({'answerable':True, 'answer':'港口小镇'}, case['answer_terms'])
    report = compare(data)
    for row in report['cases']:
        for strategy in ('budget','local'):
            row[strategy]['answer'] = {'answerable':False, 'answer':'不知道'}
    # Totals must include answer results; rescore needs no client or credentials.
    result = rescore(data, report)
    assert result['label_rescored_without_provider_calls']
    assert result['totals']['local']['answer_correct'] == 11
