"""Legacy HTTP adapter; business orchestration lives in services.agency."""
from fastapi import APIRouter
from app.schemas.agent_step import AgentStepRequest, AgentStepResponse
from app.services.agency.agent_service import agent_step

router = APIRouter(prefix="/v1/agent", tags=["agent"])
router.add_api_route("/step", agent_step, methods=["POST"], response_model=AgentStepResponse)
