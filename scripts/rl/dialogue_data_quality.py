"""Aggregate-only dataset gate audit; never prints dialogue or starts training."""
import argparse
from collections import Counter
import json
from pathlib import Path


def seed_texts(value):
    if isinstance(value,list):
        return set().union(*(seed_texts(v) for v in value)) if value else set()
    if isinstance(value,dict):
        own={v for k,v in value.items() if k in ('text','player_text','input') and isinstance(v,str)}
        nested=[seed_texts(v) for v in value.values() if isinstance(v,(dict,list))]
        return own | (set().union(*nested) if nested else set())
    return set()


def audit(rows,seeds):
    known=[r for r in rows if r.get('player_text') in seeds]
    remaining=[r for r in rows if r.get('player_text') not in seeds and r.get('source')=='llm']
    nonzero=sum(bool(r.get('relationship_delta')) for r in remaining)
    return dict(total=len(rows),known_seed_texts=len(seeds),known_seed_rows=len(known),
        llm_rows_excluding_known_seeds=len(remaining),
        remaining_by_npc=dict(Counter(r.get('companion_id','unknown') for r in remaining)),
        reward_nonzero=nonzero,
        positive=sum((r.get('relationship_delta') or 0)>0 for r in remaining),
        negative=sum((r.get('relationship_delta') or 0)<0 for r in remaining),
        missing_request_id=sum(not r.get('request_id') for r in remaining),
        count_gate_met=len(remaining)>=300 and nonzero>=30,
        provenance_verified=False,off_policy_propensities_available=False,
        training_approved=False,decision='audit remaining provenance before counting natural interaction data')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('data/runtime/dialogue_signals'))
    parser.add_argument('--seeds',type=Path,default=Path('data/test_scripts/emotion_seeds.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from scripts.support.jsonl import iter_records
    rows=[row for _,row in iter_records(args.root)]
    result=audit(rows,seed_texts(json.loads(args.seeds.read_text(encoding='utf-8'))))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
