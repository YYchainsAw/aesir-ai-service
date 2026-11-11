"""Transcribe one explicitly selected local recording with the configured backend.

Example: python -m scripts.asr_smoke --audio path/to/voice.wav
External backends send this recording to the configured provider; no retries.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from app.config import get_settings
from app.services.transcribers.base import TranscriptionError
from app.services.transcribers.factory import get_transcriber


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    if settings.asr_backend == "mock":
        print("ASR_BACKEND=mock cannot verify a real recording.", file=sys.stderr)
        return 2
    try:
        with args.audio.open("rb") as source:
            audio = source.read(settings.asr_max_audio_bytes + 1)
        if len(audio) > settings.asr_max_audio_bytes:
            raise ValueError("Recording exceeds AESIR_ASR_MAX_AUDIO_BYTES")
        started = time.monotonic()
        text = get_transcriber().transcribe(audio)
    except (OSError, ValueError, TranscriptionError) as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__, "message": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": bool(text), "backend": settings.asr_backend,
                      "elapsed_ms": round((time.monotonic() - started) * 1000),
                      "transcribed_text": text}, ensure_ascii=False))
    return 0 if text else 1


if __name__ == "__main__":
    raise SystemExit(main())
