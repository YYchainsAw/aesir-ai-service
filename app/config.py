"""Runtime configuration for the Aesir AI service."""

import os


def get_parser_backend() -> str:
    """Selects the active command-parser backend.

    Read on every call (not at import time) so it can be toggled at runtime and
    overridden in tests. Values: ``rule`` (default) or ``llm``.
    """
    return os.environ.get("AESIR_PARSER_BACKEND", "rule")