from fastapi import APIRouter

from app.schemas.tactical_order import PROTOCOL_VERSION

router = APIRouter()


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Returns immediately so UE can verify that the local service is available."""
    return {"status": "ok", "service": "aesir-ai-service", "protocol_version": PROTOCOL_VERSION}
