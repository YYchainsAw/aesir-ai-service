"""Parser abstraction: the pluggable slot where the rule parser will be joined
by an LLM adapter without changing the UE-facing Schema or the API contract.
"""

from abc import ABC, abstractmethod

from app.schemas.tactical_order import ParseCommandResponse


class CommandParser(ABC):
    """Contract implemented by every command parser backend.

    ``parse`` turns raw player text into a ``ParseCommandResponse`` whose
    ``order`` (if ``recognized``) is a whitelisted ``TacticalOrder`` that UE can
    validate and execute.
    """

    @abstractmethod
    def parse(self, text: str) -> ParseCommandResponse:
        """Parse a player text command into a UE-safe response."""