"""Legacy console HTTP routes. The page and business queries are separate."""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from app.schemas.console import ConsoleStateResponse, MemoryViewResponse, MemoryResetResponse
from app.services.console.query_service import console_state, view_memory, reset_memory

router = APIRouter(prefix="/v1/console", tags=["console"])
router.add_api_route("/state", console_state, methods=["GET"], response_model=ConsoleStateResponse)
router.add_api_route("/memory", view_memory, methods=["GET"], response_model=MemoryViewResponse)
router.add_api_route("/memory/reset", reset_memory, methods=["POST"], response_model=MemoryResetResponse)

@router.get("/ui", response_class=HTMLResponse)
def console_ui() -> str:
    return Path(__file__).with_suffix(".html").read_text(encoding="utf-8")
