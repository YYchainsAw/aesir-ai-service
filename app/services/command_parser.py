"""Public command-parsing facade.

The rule parsing logic now lives in ``parsers/rule.py``; this module keeps the
``parse_command`` entry point that ``app/api/routes.py`` depends on, selecting a
backend and falling back to the rule parser so the service never fails to answer.
"""

from app.config import get_parser_backend
from app.schemas.tactical_order import ParseCommandResponse
from app.services.parsers.rule import RuleCommandParser


def parse_command(text: str) -> ParseCommandResponse:
    """Parse player text into a UE-safe tactical order.

    Selects the backend from ``AESIR_PARSER_BACKEND`` (default ``rule``). While
    the LLM backend is unimplemented it raises ``NotImplementedError``, which we
    catch and fall back to the rule parser so utterances still resolve safely.
    """
    if get_parser_backend() == "llm":
        try:
            from app.services.parsers.llm import LLMCommandParser

            return LLMCommandParser().parse(text)
        except NotImplementedError:
            pass  # LLM backend not wired yet → fall back to the rule parser.

    return RuleCommandParser().parse(text)