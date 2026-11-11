"""Doubao synchronous recording-file ASR, using the new console API Key.

API: https://docs.volcengine.com/docs/doubao-voice/large-model-recording-file-lite-recognition-api
Only bounded PCM WAV is forwarded. Audio stays in memory; no provider retries.
"""
from __future__ import annotations

import base64
from pathlib import Path
from uuid import uuid4

import httpx

from app.config import Settings, get_settings
from app.scoped.hooks import scoped_upstream
from app.scoped.requests import timeout_for_upstream
from app.services.transcribers.base import ASRBackend, TranscriptionError, validate_pcm_wav

ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
RESOURCE_ID = "volc.bigasr.auc_turbo"


def load_api_key(settings: Settings) -> str:
    if settings.asr_volc_api_key_file.strip():
        try:
            value = Path(settings.asr_volc_api_key_file).read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeError):
            raise TranscriptionError("The private ASR credential file could not be read.") from None
    else:
        value = settings.asr_volc_api_key.get_secret_value().strip()
    if not value or any(character.isspace() for character in value):
        raise TranscriptionError("Configure a valid Doubao speech API Key before enabling external ASR.")
    return value


class VolcengineTranscriber(ASRBackend):
    def __init__(self, *, settings: Settings | None = None, http_client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self._http_client = http_client

    def transcribe(self, audio: bytes) -> str:
        if not audio:
            return ""
        validate_pcm_wav(audio, max_bytes=self.settings.asr_max_audio_bytes,
                         max_seconds=self.settings.asr_max_audio_seconds)
        api_key = load_api_key(self.settings)
        return self._recognize(audio, api_key)

    @scoped_upstream
    def _recognize(self, audio: bytes, api_key: str) -> str:
        headers = {"X-Api-Key": api_key, "X-Api-Resource-Id": RESOURCE_ID,
                   "X-Api-Request-Id": str(uuid4()), "X-Api-Sequence": "-1"}
        body = {"user": {"uid": "aesir-ai-service"},
                "audio": {"data": base64.b64encode(audio).decode("ascii")},
                "request": {"model_name": "bigmodel"}}
        timeout = timeout_for_upstream(self.settings.asr_volc_timeout_seconds)
        try:
            if self._http_client is not None:
                response = self._http_client.post(ENDPOINT, headers=headers, json=body, timeout=timeout)
            else:
                with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                    response = client.post(ENDPOINT, headers=headers, json=body)
            response.raise_for_status()
            status = response.headers.get("X-Api-Status-Code")
            if status == "20000003":  # Provider explicitly classified the recording as silence.
                return ""
            if status != "20000000":
                raise TranscriptionError("The external ASR provider did not accept the recording.")
            result = response.json()["result"]
            if not isinstance(result, dict):
                raise ValueError("Invalid result object")
            text = result.get("text")
            if not isinstance(text, str):
                raise ValueError("No text field")
            return text.strip()
        except TranscriptionError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            # Do not expose provider responses, audio or authenticated requests in public errors.
            raise TranscriptionError("External ASR is unavailable or returned an invalid response.") from None
