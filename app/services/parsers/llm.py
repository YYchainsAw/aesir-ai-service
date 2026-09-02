"""使用共享 LLM 客户端的战术指令解析器。"""

from pydantic import ValidationError

from app.schemas.tactical_order import ParseCommandResponse
from app.services.parsers.base import CommandParser
from app.services.llm.client import LLMClient, LLMClientError
from app.services.llm.factory import create_llm_client


class LLMCommandParser(CommandParser):
    """将自然语言转换为受现有 TacticalOrder Schema 限制的 JSON。"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client or create_llm_client()

    def parse(self, text: str) -> ParseCommandResponse:
        payload = self._client.generate_json(
            system_prompt=(
                "You convert Chinese ARPG tactical commands into JSON. "
                "Return only a JSON object with exactly: recognized, order, message. "
                "Use only the supported agent Eirin, target Boss, ability Explosion, and existing "
                "TacticalOrder intent/action values. Unknown commands must return recognized=false, "
                "order=null, and a short message."
            ),
            user_prompt=text,
            temperature=0.0,
        )
        try:
            return ParseCommandResponse.model_validate(payload)
        except ValidationError as error:
            raise LLMClientError("LLM tactical response does not match TacticalOrder schema.") from error
