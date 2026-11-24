import json
import pytest
from copy import deepcopy
from scripts.dialogue_review import export,summarize,RATINGS


def test_export_only_explicit_natural_full_complete_and_summary_never_leaks_text(tmp_path):
    base=dict(game_id='aesir',player_id='p',save_id='s',companion_id='alice',run_id='r',request_id='q',
        data_origin='natural',origin_authority='server_configuration',source='llm',turn_complete=True,
        text_available=True,text_mode='full',player_text='PRIVATE_PLAYER',reply_text='PRIVATE_REPLY')
    rows=[base,base,dict(base,data_origin='seed'),dict(base,text_available=False),dict(base,turn_complete=False)]
    (tmp_path/'rows.jsonl').write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8')
    reference=export(tmp_path)
    assert len(reference)==1
    reviewed=deepcopy(reference)
    assert summarize(reference,reviewed)['completed']==0
    reviewed[0].update(reviewer='human-a',ratings={key:'pass' for key in RATINGS})
    report=summarize(reference,reviewed)
    assert report['completed']==1 and 'PRIVATE_' not in str(report) and not report['training_approved']
    reviewed[0]['reply_text']='tampered'
    with pytest.raises(ValueError,match='differs'):
        summarize(reference,reviewed)


def test_duplicate_or_unauthored_ratings_cannot_inflate_completion():
    row=dict(sample_id='a',identity=[],player_text='x',reply_text='y',reviewer=None,ratings={k:'pass' for k in RATINGS})
    with pytest.raises(ValueError,match='reviewer'):
        summarize([row],[row])
    row['reviewer']='human'
    with pytest.raises(ValueError,match='duplicate'):
        summarize([row],[row,row])
