"""External-ASR wire contract and local rejection; never contacts a provider."""
import base64
import io
import json
import wave

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.services.transcribers.base import AudioValidationError, TranscriptionError
from app.services.transcribers.factory import get_transcriber
from app.services.transcribers.volcengine import ENDPOINT, RESOURCE_ID, VolcengineTranscriber, load_api_key


def wav_bytes(seconds=0.1, *, rate=16000, channels=1, width=2):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(b"\0" * int(seconds * rate) * channels * width)
    return output.getvalue()


def settings(**changes):
    return Settings(**{**dict(coordination_backend="memory", asr_volc_api_key=SecretStr("private-test-key"),
                             asr_volc_api_key_file=""), **changes})


def test_external_wire_contract_has_private_header_and_base64_audio():
    audio = wav_bytes()
    calls = []

    def provider(request):
        calls.append(request)
        assert str(request.url) == ENDPOINT
        assert request.headers["X-Api-Key"] == "private-test-key"
        assert request.headers["X-Api-Resource-Id"] == RESOURCE_ID
        assert request.headers["X-Api-Sequence"] == "-1"
        assert request.headers["X-Api-Request-Id"]
        body = json.loads(request.content)
        assert base64.b64decode(body["audio"]["data"]) == audio
        assert "private-test-key" not in request.content.decode()
        assert request.extensions["timeout"]["read"] == 20
        return httpx.Response(200, headers={"X-Api-Status-Code": "20000000"},
                              json={"result": {"text": " 艾莉，原地等我。 "}})

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        assert VolcengineTranscriber(settings=settings(), http_client=client).transcribe(audio) == "艾莉，原地等我。"
    assert len(calls) == 1


@pytest.mark.parametrize("audio,code", [
    (b"not a wav", "AUDIO_INVALID_FORMAT"),
    (wav_bytes(rate=8000), "AUDIO_INVALID_FORMAT"),
    (wav_bytes(channels=2), "AUDIO_INVALID_FORMAT"),
    (wav_bytes(width=1), "AUDIO_INVALID_FORMAT"),
    (wav_bytes()[:-10], "AUDIO_INVALID_FORMAT"),
    (wav_bytes(seconds=0), "AUDIO_INVALID_FORMAT"),
    (wav_bytes(seconds=0.3), "AUDIO_TOO_LONG"),
], ids=["invalid-header", "wrong-rate", "stereo", "wrong-width", "truncated", "no-frames", "too-long"])
def test_bad_audio_is_rejected_before_provider(audio, code):
    def never(request):
        pytest.fail("Invalid audio was sent externally")

    with httpx.Client(transport=httpx.MockTransport(never)) as client:
        adapter = VolcengineTranscriber(settings=settings(asr_max_audio_seconds=0.2), http_client=client)
        with pytest.raises(AudioValidationError) as caught:
            adapter.transcribe(audio)
    assert caught.value.code == code


def test_size_limit_is_checked_before_provider():
    with pytest.raises(AudioValidationError) as caught:
        VolcengineTranscriber(settings=settings(asr_max_audio_bytes=44)).transcribe(wav_bytes())
    assert caught.value.status_code == 413


@pytest.mark.parametrize("status,headers,body", [
    (401, {}, {"error": "private-test-key"}),
    (200, {"X-Api-Status-Code": "45000001"}, {"result": {"text": "must not return this"}}),
    (200, {}, {"result": {"text": "unverified"}}),
    (200, {"X-Api-Status-Code": "20000000"}, {"result": []}),
    (200, {"X-Api-Status-Code": "20000000"}, {"result": {"text": 123}}),
])
def test_provider_errors_do_not_become_mock_or_expose_credentials(status, headers, body):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, headers=headers, json=body))) as client:
        adapter = VolcengineTranscriber(settings=settings(), http_client=client)
        with pytest.raises(TranscriptionError) as caught:
            adapter.transcribe(wav_bytes())
    assert "private-test-key" not in str(caught.value)


def test_timeout_is_not_retried():
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("private-test-key")

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(TranscriptionError, match="unavailable"):
            VolcengineTranscriber(settings=settings(), http_client=client).transcribe(wav_bytes())
    assert len(calls) == 1


def test_silence_and_empty_audio_return_no_invented_text():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"X-Api-Status-Code": "20000003"}))) as client:
        adapter = VolcengineTranscriber(settings=settings(), http_client=client)
        assert adapter.transcribe(wav_bytes()) == ""
        assert adapter.transcribe(b"") == ""


def test_private_key_file_takes_precedence_and_missing_file_is_explicit(tmp_path):
    key = tmp_path / "speech-key"
    key.write_text("file-key\n", encoding="utf-8")
    assert load_api_key(settings(asr_volc_api_key_file=str(key))) == "file-key"
    with pytest.raises(TranscriptionError, match="could not be read"):
        load_api_key(settings(asr_volc_api_key_file=str(tmp_path / "missing")))
    with pytest.raises(TranscriptionError, match="Configure"):
        load_api_key(settings(asr_volc_api_key=SecretStr("")))


def test_factory_selects_external_and_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("AESIR_ASR_BACKEND", "volcengine")
    assert isinstance(get_transcriber(), VolcengineTranscriber)
    monkeypatch.setenv("AESIR_ASR_BACKEND", "typo")
    with pytest.raises(TranscriptionError, match="Unknown ASR backend"):
        get_transcriber()
