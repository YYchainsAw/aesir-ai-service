"""Economy options reach both HTTP paths without changing other providers."""
import json

import httpx
import pytest

from app.config import get_settings
from app.services.llm.client import OpenAICompatibleLLMClient, OpenAICompatibleSettings
from app.services.llm.factory import create_llm_client


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("options", [{}, {"thinking_mode": "disabled", "max_tokens": 1024}])
def test_generation_options_apply_to_both_http_paths(stream, options):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        if stream:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"{}"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = OpenAICompatibleLLMClient(OpenAICompatibleSettings(
            api_key="test-key", model="test-model", base_url="https://provider.test", **options), http_client=http)
        if stream:
            assert list(client.stream_completion(system_prompt="JSON", user_prompt="hello")) == ["{}"]
        else:
            assert client.generate_json(system_prompt="JSON", user_prompt="hello") == {}
    if options:
        assert requests[0]["thinking"] == {"type": "disabled"}
        assert requests[0]["max_tokens"] == 1024
    else:
        assert "thinking" not in requests[0] and "max_tokens" not in requests[0]


def test_factory_reads_economy_options(monkeypatch):
    captured = []
    monkeypatch.setenv("LLM_THINKING_MODE", "disabled")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1024")
    monkeypatch.setattr("app.services.llm.factory.OpenAICompatibleLLMClient", lambda settings: captured.append(settings))
    create_llm_client()
    assert captured[0].thinking_mode == "disabled"
    assert captured[0].max_tokens == 1024


@pytest.mark.parametrize("name,value", [("LLM_THINKING_MODE", "false"), ("LLM_MAX_TOKENS", "0")])
def test_invalid_generation_options_rejected(monkeypatch, name, value):
    from pydantic import ValidationError

    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        get_settings()
