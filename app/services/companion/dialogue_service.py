"""陪伴对话服务的首版实现。

这里刻意不调用 LLM。先固定输出 UE 能消费的文本、情绪和动作 ID，保证 UE 可以
独立完成非战斗对话表现。后续由 LLM 实现替换此函数内部逻辑即可。
"""

from app.schemas.companion_dialogue import (
    CompanionDialogueRequest,
    CompanionDialogueResponse,
)


def create_mock_dialogue_reply(
    request: CompanionDialogueRequest,
) -> CompanionDialogueResponse:
    """返回稳定、可预测的临时陪伴对话响应。"""
    return CompanionDialogueResponse(
        companion_id=request.companion_id,
        reply_text="我在。有什么想和我说的吗？",
        emotion_id="emotion.calm",
        gesture_id="gesture.attentive_idle",
        facial_expression_id="face.gentle_smile",
        interruptible=True,
        source="mock",
    )
