"""Offline synthetic counterexamples; reports failures rather than hiding them."""
import argparse
from collections import Counter
import json
from pathlib import Path
from app.services.memory.facts import is_grounded,content_chars,normalize_fact


def evaluate(data):
    rows=[]
    for case in data['cases']:
        chars=content_chars(case['fact'])
        sources=set().union(*(set(normalize_fact(text)) for text in case['sources'])) if case['sources'] else set()
        baseline=len(chars)>=2 and len(chars & sources)/len(chars)>=0.5
        actual=is_grounded(case['fact'],case['sources'])
        rows.append(dict(name=case['name'],category=case['category'],expected=case['expected'],baseline=baseline,hardened=actual))
    totals={strategy:dict(cases=len(rows),correct=sum(row[strategy]==row['expected'] for row in rows),
        false_accepts=sum(row[strategy] and not row['expected'] for row in rows),
        false_rejects=sum(not row[strategy] and row['expected'] for row in rows)) for strategy in ('baseline','hardened')}
    return dict(synthetic=True,provider_calls=0,cases=rows,totals=totals,
        remaining=[dict(name=row['name'],category=row['category']) for row in rows if row['hardened']!=row['expected']],
        limits='Hand-authored counterexamples, not natural-player accuracy or general entailment verification')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,default=Path('data/evals/fact_grounding_boundaries.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=evaluate(json.loads(args.fixture.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['totals']))


if __name__=='__main__':
    main()
