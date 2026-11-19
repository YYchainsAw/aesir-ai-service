import json
import httpx
import pytest
from app.config import get_settings
from app.services.companion.dialogue_signals import record_turn_signal, quality_candidates
from app.services.companion.dialogue_service import _fallback_reason
from app.services.llm.client import LLMClientError


@pytest.mark.parametrize('origin', ['natural','seed','fault','evaluation'])
def test_server_origin_partitions_signal_files(origin, monkeypatch, tmp_path):
    monkeypatch.setenv('AESIR_DIALOGUE_SIGNALS_DIR', str(tmp_path))
    monkeypatch.setenv('AESIR_DIALOGUE_DATA_ORIGIN', origin)
    monkeypatch.setenv('AESIR_DIALOGUE_DATA_RUN_ID', 'p1')
    record_turn_signal('companion.alice','session',player_text='你好',reply_text='我已经释放技能',
        source='fallback', emotion_id='',gesture_id='',facial_expression_id='',game_state='conversation',
        style_violations=[{'category':'unsupported_observation'}])
    row = json.loads((tmp_path/'aesir'/origin/'p1'/'companion.alice.jsonl').read_text(encoding='utf-8'))
    assert row['data_origin'] == origin and row['origin_authority'] == 'server_configuration'
    assert row['fallback_reason'] == 'style_guard'
    assert row['quality_review']['execution_claim_candidate']
    assert row['quality_review']['unsupported_narrative_candidate']
    assert row['quality_review']['semantic_factuality'] == 'unverified'


@pytest.mark.parametrize('run_id', ['../natural', '.', '..', 'tag.'])
def test_origin_run_cannot_escape_directory(monkeypatch, run_id):
    monkeypatch.setenv('AESIR_DIALOGUE_DATA_RUN_ID', run_id)
    with pytest.raises(ValueError):
        get_settings()


def test_fallback_diagnostics_use_categories_without_provider_text():
    class Service:
        last_style_violations = []
    error = LLMClientError('secret provider detail')
    error.__cause__ = httpx.ReadTimeout('private URL')
    assert _fallback_reason(error, Service()) == 'upstream_timeout'
    error.__cause__ = httpx.HTTPStatusError('private URL',request=httpx.Request('POST','https://example.invalid'),
                                        response=httpx.Response(401))
    assert _fallback_reason(error, Service()) == 'upstream_auth'
    Service.last_style_violations = [{'category':'fabrication_signal'}]
    assert _fallback_reason(error, Service()) == 'style_guard'


def test_seed_runner_overrides_natural_and_restores_configuration(monkeypatch, tmp_path):
    from scripts.emotion_regression import seed_capture
    monkeypatch.setenv('AESIR_DIALOGUE_DATA_ORIGIN','natural')
    monkeypatch.setenv('AESIR_DIALOGUE_DATA_RUN_ID','live')
    monkeypatch.setenv('AESIR_DIALOGUE_SIGNALS_DIR', str(tmp_path))
    with pytest.raises(RuntimeError):
        with seed_capture() as root:
            assert get_settings().dialogue_data_origin == 'seed'
            assert root.parent.name == 'seed'
            raise RuntimeError('interrupted')
    assert get_settings().dialogue_data_origin == 'natural'
    assert get_settings().dialogue_data_run_id == 'live'


def test_stream_transport_failure_is_a_fault_record_and_never_a_completed_turn(monkeypatch, tmp_path):
    from app.schemas.companion_dialogue import CompanionDialogueRequest
    from app.services.companion import dialogue_service as dialogue
    from app.services.companion.llm_dialogue_service import StreamEvent
    from app.services.companion.session_memory import get_session_memory
    monkeypatch.setenv('AESIR_COMPANION_BACKEND', 'llm')
    monkeypatch.setenv('AESIR_DIALOGUE_DATA_ORIGIN', 'fault')
    monkeypatch.setenv('AESIR_DIALOGUE_SIGNALS_DIR', str(tmp_path))
    class Broken:
        last_style_violations = []
        def __init__(self, **kwargs):
            pass
        def stream_reply(self, *args, **kwargs):
            yield StreamEvent(kind='delta', text='刚才')
            raise LLMClientError('private detail') from httpx.ReadTimeout('private endpoint')
    monkeypatch.setattr(dialogue, 'LLMCompanionDialogueService', Broken)
    request = CompanionDialogueRequest(text='你好',session_id='fault-test',companion_id='companion.alice')
    frames = list(dialogue.stream_dialogue_reply(request))
    assert [frame.kind for frame in frames] == ['delta','error']
    row = json.loads((tmp_path/'aesir'/'fault'/'companion.alice.jsonl').read_text(encoding='utf-8'))
    assert not row['turn_complete'] and row['source'] == 'llm_interrupted'
    assert row['fallback_reason'] == 'upstream_timeout'
    assert 'private detail' not in str(row) and 'private endpoint' not in str(row)
    assert not get_session_memory(get_settings().dialogue_history_turns).history('fault-test','companion.alice')
