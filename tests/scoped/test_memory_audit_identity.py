import json
import os
from pathlib import Path

from test_scoped_api import h


def test_dialogue_audit_carries_current_logical_request_and_scope(h):
    context = h.bind()
    body = h.chat(context)
    response = h.client.post('/v1/scoped/companion/chat', json=body)
    assert response.status_code == 200, response.text
    def rows():
        return [json.loads(line)
                for path in Path(os.environ['AESIR_DIALOGUE_SIGNALS_DIR']).rglob('*.jsonl')
                for line in path.read_text(encoding='utf-8').splitlines()]
    row = next(row for row in rows() if row.get('request_id') == body['request_id'])
    assert row['player_id'] == context['scope']['player_id']
    assert row['save_id'] == context['scope']['save_id']
    assert row['run_id'] == context['run_id']
    assert row['memory_epoch'] == context['memory_epoch']
    assert h.client.post('/v1/scoped/companion/chat', json=body).json() == response.json()
    assert sum(row.get('request_id') == body['request_id'] for row in rows()) == 1
