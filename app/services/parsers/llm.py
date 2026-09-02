"""LLM-backed command parser (Phase-2 slot, not yet wired).

Kept deliberately structural: no LLM SDK dependency is introduced in the
skeleton. The actual integration steps live behind the ``parse`` TODO below —
inject a client (OpenAI-compatible / Ark / etc.), build the prompt, request
structured JSON, validate against the ``TacticalOrder`` whitelist, and return a
``ParseCommandResponse``. The facade falls back to the rule parser until then.
"""

from app.schemas.tactical_order import ParseCommandResponse
from app.services.parsers.base import CommandParser


class LLMCommandParser(CommandParser):
    """Phase-2 slot for an LLM-backed parser.

    TODO(phase-2): inject an LLM client, build the prompt from the player text,
    request structured JSON constrained to the ``TacticalOrder`` whitelist, and
    validate the result into a ``ParseCommandResponse``. Not wired yet.
    """

    def parse(self, text: str) -> ParseCommandResponse:
        raise NotImplementedError("AESIR_PARSER_BACKEND=llm is not implemented yet.")