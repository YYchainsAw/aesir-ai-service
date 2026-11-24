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
    origins = ('natural', 'seed', 'fault', 'evaluation', 'unknown')
    def origin(row):
        value = row.get('data_origin', 'unknown')
        return value if value in origins and row.get('origin_authority') == 'server_configuration' else 'unknown'
    classified = {name: [row for row in rows if origin(row) == name] for name in origins}
    # One logical request can appear in retries/log copies. It counts once.
    seen = set()
    natural = []
    for row in classified['natural']:
        identity = tuple(row.get(key) for key in ('game_id','player_id','save_id','companion_id','run_id','request_id'))
        if (not all(identity) or identity in seen or row.get('player_text') in seeds
                or row.get('source') != 'llm' or row.get('turn_complete') is not True):
            continue
        seen.add(identity)
        natural.append(row)
    natural_rewards = sum(bool(row.get('relationship_delta')) for row in natural)
    quality = {}
    for name, group in classified.items():
        quality[name] = dict(rows=len(group),
            missing_completion_status=sum('turn_complete' not in r for r in group),
            missing_quality_review=sum(not r.get('quality_review') for r in group),
            semantic_factuality_unverified=sum((r.get('quality_review') or {}).get('semantic_factuality') != 'verified' for r in group),
            by_source=dict(Counter(r.get('source', 'unknown') for r in group)),
            incomplete=sum(r.get('turn_complete') is False for r in group),
            repetitive=sum(bool(r.get('repetitive')) for r in group),
            negative_feedback=sum(bool((r.get('signals') or {}).get('negative_feedback')) for r in group),
            facts_rejected=sum(r.get('facts_rejected', 0) or 0 for r in group),
            unsupported_narrative_candidates=sum(bool((r.get('quality_review') or {}).get('unsupported_narrative_candidate')) for r in group),
            execution_claim_candidates=sum(bool((r.get('quality_review') or {}).get('execution_claim_candidate')) for r in group),
            fallback_reasons=dict(Counter(r.get('fallback_reason', 'unrecorded') for r in group if r.get('source') != 'llm')),
            style_categories=dict(Counter(v.get('category', 'unknown') if isinstance(v, dict) else str(v)
                for r in group for v in r.get('style_violations') or [])))
    return dict(total=len(rows),known_seed_texts=len(seeds),known_seed_rows=len(known),
        llm_rows_excluding_known_seeds=len(remaining),
        remaining_by_npc=dict(Counter(r.get('companion_id','unknown') for r in remaining)),
        reward_nonzero=nonzero,
        positive=sum((r.get('relationship_delta') or 0)>0 for r in remaining),
        negative=sum((r.get('relationship_delta') or 0)<0 for r in remaining),
        missing_request_id=sum(not r.get('request_id') for r in remaining),
        count_gate_met=len(remaining)>=300 and nonzero>=30,
        quality_by_origin=quality, attributed_natural_unique_complete_llm=len(natural),
        attributed_natural_text_available=sum(r.get('text_available') is True for r in natural),
        attributed_natural_reward_nonzero=natural_rewards,
        natural_count_gate_met=len(natural)>=300 and natural_rewards>=30,
        provenance_verified=False,off_policy_propensities_available=False,
        training_approved=False,decision='Only explicitly attributed natural requests count toward the natural gate; semantic review and training approval remain separate')


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
