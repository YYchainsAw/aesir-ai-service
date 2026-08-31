from fastapi import APIRouter

from app.schemas.tactical_order import ParseCommandRequest, ParseCommandResponse
from app.services.command_parser import parse_command

router = APIRouter()


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Returns immediately so UE can verify that the local service is available."""
    return {"status": "ok", "service": "aesir-ai-service", "protocol_version": "1.0"}


@router.post("/parse-command", response_model=ParseCommandResponse, tags=["commands"])
def parse_tactical_command(request: ParseCommandRequest) -> ParseCommandResponse:
    """Converts a player command into a UE-safe tactical order."""
    return parse_command(request.text)
