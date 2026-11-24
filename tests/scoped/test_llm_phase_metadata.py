import json
import httpx
from uuid import uuid4
from app.scoped.context import use_scope
from app.scoped.trace import request_trace
from app.services.llm.client import OpenAICompatibleLLMClient, OpenAICompatibleSettings
from test_scoped_api import h


def test_usage_whitelist_and_first_content_observation_do_not_log_payload(h,monkeypatch,tmp_path):
    monkeypatch.setenv('AESIR_REQUEST_TRACES_DIR',str(tmp_path))
    def handler(request):
        if json.loads(request.content).get('stream'):
            chunks=''.join('data: '+json.dumps({'choices':[{'delta':{'content':c}}]})+'\n\n' for c in ['好','呀'])
            return httpx.Response(200,text=chunks+'data: [DONE]\n\n')
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"answer":"PRIVATE_REPLY"}'}}],
            'usage':{'prompt_tokens':17,'completion_tokens':4,'private':'PRIVATE_USAGE','total_tokens':True}})
    model=OpenAICompatibleLLMClient(OpenAICompatibleSettings('synthetic-key','synthetic-model','https://example.invalid'),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    active=h.scope(h.bind())
    with use_scope(active),request_trace(active,'chat',uuid4()):
        model.generate_json(system_prompt='PRIVATE_SYSTEM',user_prompt='PRIVATE_INPUT')
        assert list(model.stream_completion(system_prompt='PRIVATE_SYSTEM',user_prompt='PRIVATE_INPUT'))==['好','呀']
    raw=''.join(p.read_text(encoding='utf-8') for p in tmp_path.rglob('*.jsonl'))
    assert 'PRIVATE_' not in raw and 'synthetic-key' not in raw
    rows=[json.loads(line) for line in raw.splitlines()]
    usage=next(row for row in rows if row['event']=='llm_usage')
    assert usage['prompt_tokens']==17 and 'total_tokens' not in usage
    first=[row for row in rows if row['event']=='llm_first_content']
    assert len(first)==1 and first[0]['elapsed_ms']>=0
    stage=next(row for row in rows if row.get('stage')=='llm_stream')
    assert stage['outcome']=='returned'
