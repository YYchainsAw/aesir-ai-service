import json
import os
from datetime import datetime, timezone
from pathlib import Path
from app.services.companion.dialogue_signals import record_turn_signal
from app.services.companion.signal_files import write_signal
from scripts.prune_dialogue_signals import prune


def test_metadata_mode_removes_text_topics_and_matched_fragments(monkeypatch,tmp_path):
    monkeypatch.setenv('AESIR_DIALOGUE_SIGNAL_TEXT_MODE','metadata')
    monkeypatch.setenv('AESIR_DIALOGUE_SIGNALS_DIR',str(tmp_path))
    record_turn_signal('companion.alice','test',player_text='PRIVATE_PLAYER',reply_text='PRIVATE_REPLY',
        source='llm',emotion_id='',gesture_id='',facial_expression_id='',game_state='conversation',
        injected_topics=['PRIVATE_TOPIC'],style_violations=[dict(category='meta_term',matched_term='PRIVATE_MATCH',message='PRIVATE_MESSAGE')])
    raw=next(tmp_path.rglob('*.jsonl')).read_text(encoding='utf-8')
    assert 'PRIVATE_' not in raw
    row=json.loads(raw)
    assert row['text_mode']=='metadata' and not row['text_available']
    assert row['injected_topic_count']==1 and row['style_violations']==[{'category':'meta_term'}]


def test_rotation_preserves_all_rows_and_retention_only_deletes_old_archives(tmp_path):
    name='companion.alice.jsonl'
    first=json.dumps({'text':'a'*2000})
    second=json.dumps({'text':'b'*2000})
    write_signal(tmp_path,name,first,3000)
    write_signal(tmp_path,name,second,3000)
    archive=next(tmp_path.glob('*.archive-*.jsonl'))
    assert archive.read_text().strip()==first
    assert (tmp_path/name).read_text().strip()==second
    os.utime(archive,(1,1))
    unrelated=tmp_path/'request-journal.jsonl'
    unrelated.write_text('must stay')
    assert prune(tmp_path,30)['candidates']==1
    assert archive.exists()
    assert prune(tmp_path,30,apply=True)['deleted']==1
    assert unrelated.exists() and (tmp_path/name).exists()
