"""Legacy world-event HTTP adapter."""
from fastapi import APIRouter
from app.schemas.world_event import WorldEventResponse
from app.services.tactical.world_service import report_world_event
router = APIRouter(prefix="/v1/world", tags=["world"])
router.add_api_route("/events", report_world_event, methods=["POST"], response_model=WorldEventResponse)
