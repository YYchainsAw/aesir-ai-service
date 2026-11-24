import json
from uuid import uuid4
import pytest
from app.scoped.context import use_scope
from app.scoped.trace import request_trace, measure_stage
from test_scoped_api import h


def test_stage_diagnostics_keep_scope_ids_and_never_exception_text(h,monkeypatch,tmp_path):
    monkeypatch.setenv('AESIR_REQUEST_TRACES_DIR',str(tmp_path))
    active=h.scope(h.bind())
    rid=uuid4()
    with use_scope(active),request_trace(active,'chat',rid):
        with measure_stage('memory_retrieval'):
            pass
        with pytest.raises(ValueError):
            with measure_stage('test_failure'):
                raise ValueError('PRIVATE_FAILURE_DETAIL')
    raw=''.join(path.read_text(encoding='utf-8') for path in tmp_path.rglob('*.jsonl'))
    assert 'PRIVATE_FAILURE_DETAIL' not in raw
    rows=[json.loads(line) for line in raw.splitlines()]
    stages=[row for row in rows if row['event']=='stage_finished']
    assert [row['outcome'] for row in stages]==['returned','interrupted']
    assert all(row['elapsed_ms']>=0 and row['logical_request_id']==str(rid) for row in stages)
