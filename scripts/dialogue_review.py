"""Explicit private export and manual scoring; never fabricates player reviews.

Export only attributed natural/full/complete LLM rows. Files include private
dialogue and belong outside Git (for example data/runtime/review). The summary
command prints aggregates only; unknown/unrated values never count as passes.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from scripts.support.jsonl import iter_records

RATINGS=('memory_accuracy','naturalness','refusal_quality','execution_honesty')


def export(root):
    from scripts.rl.dialogue_data_quality import seed_texts
    seed_path=Path(__file__).resolve().parents[1]/'data/test_scripts/emotion_seeds.json'
    seeds=seed_texts(json.loads(seed_path.read_text(encoding='utf-8'))) if seed_path.exists() else set()
    result=[]
    seen=set()
    for _,row in iter_records(root):
        keys=('game_id','player_id','save_id','companion_id','run_id','request_id')
        identity=tuple(row.get(k) for k in keys)
        if (not all(identity) or identity in seen or row.get('data_origin')!='natural'
            or row.get('origin_authority')!='server_configuration' or row.get('source')!='llm'
            or row.get('turn_complete') is not True or row.get('text_available') is not True or row.get('text_mode')!='full'
            or row.get('player_text') in seeds
            or not isinstance(row.get('player_text'),str) or not isinstance(row.get('reply_text'),str)):
            continue
        seen.add(identity)
        payload={'identity':identity,'player_text':row['player_text'],'reply_text':row['reply_text']}
        digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        result.append(dict(sample_id=digest,**payload,reviewer=None,ratings={key:None for key in RATINGS},notes=''))
    return result


def summarize(reference, reviewed):
    expected={row['sample_id']:row for row in reference}
    if len(expected)!=len(reference):
        raise ValueError('Duplicate reference sample')
    seen=set(); counts={key:Counter() for key in RATINGS}; completed=0
    for row in reviewed:
        sample=row.get('sample_id')
        if sample not in expected or sample in seen:
            raise ValueError('Unknown or duplicate review sample')
        seen.add(sample)
        original=expected[sample]
        if any(row.get(key)!=original.get(key) for key in ('identity','player_text','reply_text')):
            raise ValueError('Review content differs from the exported sample')
        ratings=row.get('ratings',{})
        if set(ratings)!=set(RATINGS) or any(value not in (None,'pass','fail','unknown','not_applicable') for value in ratings.values()):
            raise ValueError('Invalid review ratings')
        if any(value not in (None,'unknown') for value in ratings.values()) and not str(row.get('reviewer') or '').strip():
            raise ValueError('Rated samples require a reviewer')
        for key,value in ratings.items():
            counts[key][value or 'unrated']+=1
        completed+=all(value in ('pass','fail','not_applicable') for value in ratings.values())
    return dict(exported=len(reference),reviewed=len(seen),missing=len(reference)-len(seen),
        distinct_players=len({row['identity'][1] for row in reference if len(row.get('identity',[]))>=2}),
        completed=completed,ratings={key:dict(value) for key,value in counts.items()},
        training_approved=False,semantic_review='human ratings; not an automatic truth verdict')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    out=subs.add_parser('export');out.add_argument('--root',type=Path,required=True);out.add_argument('--output',type=Path,required=True)
    report=subs.add_parser('summary');report.add_argument('--reference',type=Path,required=True);report.add_argument('--reviewed',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='export':
        rows=export(args.root)
        if args.output.exists():
            parser.error('Output exists; choose a new file to preserve prior reviews')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream:
            json.dump(rows,stream,ensure_ascii=False,indent=2)
        print(json.dumps({'exported':len(rows),'contains_private_text':bool(rows),'automatic_ratings':False}))
    else:
        print(json.dumps(summarize(json.loads(args.reference.read_text(encoding='utf-8')),
            json.loads(args.reviewed.read_text(encoding='utf-8'))),ensure_ascii=False))


if __name__=='__main__':
    main()
