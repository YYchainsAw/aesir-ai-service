"""SQL-backed offline factual sync; no old binding or executable response."""
from uuid import UUID

from fastapi import APIRouter, Depends

from app.persistence.auth import reserve_request_quota, use_principal
from app.persistence.sync import sync_facts, sync_state
from app.scoped.identity import Principal, require_permission, resolve_npc_scope
from app.schemas.sync import SyncFactsRequest, SyncFactsResponse, SyncStateResponse

router = APIRouter(prefix="/v1/scoped/sync", tags=["scoped-sync-v0.4"])


@router.get("/state", response_model=SyncStateResponse)
def authoritative_state(save_id: UUID, companion_id: str,
                        principal: Principal = Depends(require_permission("npc:use"))):
    npc = resolve_npc_scope(principal, save_id, companion_id)
    with use_principal(principal):
        reserve_request_quota(principal, npc.game_id)
        return sync_state(npc, principal)


@router.post("/facts", response_model=SyncFactsResponse)
def confirm_facts(request: SyncFactsRequest, principal: Principal = Depends(require_permission("npc:use"))):
    npc = resolve_npc_scope(principal, request.save_id, request.companion_id)
    with use_principal(principal):
        reserve_request_quota(principal, npc.game_id)
        return sync_facts(npc, principal, request)
