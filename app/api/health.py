from fastapi import APIRouter

from app.schemas.tactical_order import PROTOCOL_VERSION
from app.services.system.version import get_service_commit

router = APIRouter()


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Returns immediately so UE can verify that the local service is available.

    ``service_commit`` 为运行时 git short SHA（T21 / #34），UE 侧据此确认当前
    跑的是哪个 commit，无需读代码即可复现。
    """
    return {
        "status": "ok",
        "service": "aesir-ai-service",
        "protocol_version": PROTOCOL_VERSION,
        "service_commit": get_service_commit(),
    }
