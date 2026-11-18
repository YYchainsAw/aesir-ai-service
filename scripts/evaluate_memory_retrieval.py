"""Offline M1 comparison; no provider calls and no change to live retrieval.

Candidate models an index of summaries/tags followed by one batched full-text
read. Character counts are payload sizes, NOT provider tokens or billed cost.
Local lookup timings exclude network/model tool selection latency.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from time import perf_counter_ns

from app.schemas.memory import MemoryEntry, MemorySnapshot
from app.services.memory.retrieval import format_memory_block, retrieve


@dataclass
class Snapshot:
    value: MemorySnapshot

    def snapshot(self):
        return self.value


def compare(data: dict) -> dict:
    entries = [MemoryEntry.model_validate(entry) for entry in data['entries']]
    by_id = {str(e.entry_id): e for e in entries}
    if len(by_id) != len(entries):
        raise ValueError('Duplicate entry IDs')
    active = {key: e for key, e in by_id.items() if e.superseded_by is None}
    index = [{key: item[key] for key in ('entry_id', 'summary', 'terms')}
             for item in data['index'] if item['entry_id'] in active]
    if any(item['entry_id'] not in by_id for item in data['index']):
        raise ValueError('Index references an unknown entry')
    index_chars = len(json.dumps(index, ensure_ascii=False))
    rows = []
    for case in data['cases']:
        expected = set(case['expected'])
        if not expected <= active.keys():
            raise ValueError('Expected IDs must be active corpus entries')
        budget = data['budget']
        started = perf_counter_ns()
        baseline = retrieve(Snapshot(MemorySnapshot(archive=entries)), budget=budget)
        baseline_ms = (perf_counter_ns() - started) / 1e6
        started = perf_counter_ns()
        query = case['query'].casefold()
        # Deliberately simple deterministic selector, not a claim of semantic RAG.
        ranked = sorted(index, key=lambda item: sum(term.casefold() in query
                        for term in item['terms']), reverse=True)
        selected = [item for item in ranked if any(term.casefold() in query
                    for term in item['terms'])][:budget]
        candidate = [active[item['entry_id']] for item in selected]
        candidate_ms = (perf_counter_ns() - started) / 1e6
        result = dict(case=case['name'], query=case['query'], expected=sorted(expected))
        for name, found, elapsed in [('budget', baseline, baseline_ms),
                                     ('index_read', candidate, candidate_ms)]:
            ids = {str(e.entry_id) for e in found}
            payload = len(format_memory_block(found))
            result[name] = dict(ids=sorted(ids), correct=len(ids & expected),
                false_recall=len(ids - expected), omitted=len(expected - ids),
                exact=ids == expected, payload_chars=payload + (index_chars if name == 'index_read' else 0),
                local_lookup_ms=round(elapsed, 4), extra_reads=int(name == 'index_read' and bool(found)))
        rows.append(result)
    totals = {}
    for strategy in ('budget', 'index_read'):
        counts = {key: sum(row[strategy][key] for row in rows)
                  for key in ('correct', 'false_recall', 'omitted', 'payload_chars', 'extra_reads')}
        counts['exact_cases'] = sum(row[strategy]['exact'] for row in rows)
        counts['precision'] = counts['correct'] / max(1, counts['correct'] + counts['false_recall'])
        counts['recall'] = counts['correct'] / max(1, counts['correct'] + counts['omitted'])
        totals[strategy] = counts
    return dict(cases=rows, totals=totals, limits=dict(synthetic=True, live_strategy_changed=False,
        provider_tokens_measured=False, model_accuracy_measured=False,
        tool_network_latency_measured=False), decision='retain_budget_pending_representative_model_tool_evaluation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, default=Path('data/evals/memory_retrieval.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(json.loads(args.fixture.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report['totals'], ensure_ascii=False))


if __name__ == '__main__':
    main()
