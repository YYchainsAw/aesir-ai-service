import pytest

from app.schemas.agent_step import AgentStepRequest
from app.services.agency.agent_service import agent_step
from app.services.tactical.intent_parser import is_unsupported_basic_attack


@pytest.mark.parametrize('text', ['艾莉，普通攻击Boss。', '艾莉，普攻！', 'alice, basic attack boss', '艾莉，立即发射奥术弹'])
@pytest.mark.parametrize('backend', ['rule', 'llm'])
def test_basic_attack_is_rejected_before_any_llm_or_directive(text, backend, monkeypatch):
    import json
    from pathlib import Path
    monkeypatch.setenv('AESIR_INTENT_BACKEND', backend)
    def unexpected(*args, **kwargs):
        raise AssertionError('unsupported attack must not reach model or dialogue')
    monkeypatch.setattr('app.services.tactical.llm_intent.parse_intent_with_source', unexpected)
    monkeypatch.setattr('app.services.companion.dialogue_service.create_dialogue_reply', unexpected)
    data = json.loads(Path('data/golden/scoped/agent_step_request.json').read_text(encoding='utf-8'))
    # Exercise the shared dispatcher without scoped transport metadata.
    for key in ('save_id','run_id','run_binding_id','memory_epoch','service_instance_id','timing'):
        data.pop(key, None)
    data.update(protocol_version='0.3', text=text)
    response = agent_step(AgentStepRequest.model_validate(data))
    assert response.action == 'none' and response.directive is None
    assert response.observability.source == 'rule'
    assert 'BASIC_ATTACK_NOT_SUPPORTED' in response.observability.reason_codes
    assert 'CHITCHAT_DIALOGUE' not in response.observability.reason_codes


@pytest.mark.parametrize('text', ['布鲁诺，普攻Boss', '艾莉，普通攻击是什么？', '艾莉，不要普攻', '艾莉，爆裂魔法', '今天天气不错'])
def test_questions_other_persona_negations_and_supported_burst_are_not_reclassified(text):
    assert not is_unsupported_basic_attack(text, wake_words=('艾莉', 'alice'))
