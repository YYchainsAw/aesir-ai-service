from fastapi import APIRouter, HTTPException, status

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)
from app.services.companion.dialogue_service import create_dialogue_reply
from app.services.companion.profile_repository import UnknownCompanionError

router = APIRouter(prefix="/v1/companion", tags=["companion"])


@router.post("/chat", response_model=CompanionDialogueResponse)
def chat_with_companion(request: CompanionDialogueRequest) -> CompanionDialogueResponse:
    """返回非战斗陪伴对话的模拟响应。

    仅允许 exploration / conversation 状态调用；战斗战术必须继续使用独立接口。
    """
    try:
        return create_dialogue_reply(request)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
