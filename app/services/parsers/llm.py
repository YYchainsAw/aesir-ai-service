"""使用共享 LLM 客户端的战术指令解析器。"""

from pydantic import ValidationError

import json

import httpx
from pydantic import TypeAdapter

from app.config import get_llm_api_key, get_llm_base_url, get_llm_model, get_llm_timeout
from app.schemas.tactical_order import ParseCommandResponse, TacticalOrder
from app.services.parsers.base import CommandParser
from app.services.llm.client import LLMClient, LLMClientError
from app.services.llm.factory import create_llm_client


class LLMError(Exception):
    """LLM 解析链路中的任何失败（配置缺失、网络、非法输出）。"""


class LLMNotConfiguredError(LLMError):
    """未配置 LLM API key 时抛出。"""


# 系统提示：把手写的白名单契约喂给 LLM，并要求只输出 JSON。
SYSTEM_PROMPT = """你是一名游戏《Aesir》的战术指令解析器。玩家的指令都发给队友艾琳（Eirin）。
请把中文自然语言指令解析为受限的 JSON 对象，只输出 JSON，不要任何解释或代码块围栏。

输出对象结构：
{"recognized": true, "order": {"protocol_version": "1.0", "agent": "Eirin", "priority": "high", "expires_on": "EncounterEnd", "intent": "<intent>", ...按意图填字段}, "message": "简短英文说明"}
无法识别为任何意图时输出 {"recognized": false, "order": null, "message": "Command not recognized."}

intent 及对应字段（所有值必须严格使用枚举白名单，不能发明）：
1. conditional_cast :
   {"intent": "conditional_cast", "trigger": {"target": "Boss", "state": "Stunned"}, "action": {"type": "CastAbility", "ability_id": "Explosion"}}
   适用：当 Boss 眩晕/被控时施放技能。
2. hold_ability :
   {"intent": "hold_ability", "action": {"type": "HoldAbility", "ability_id": "Explosion"}}
   适用：暂时保留/不用某个技能。
3. retreat :
   {"intent": "retreat", "action": {"type": "Retreat"}}
   适用：撤退、后撤、优先保命。
4. follow_keep_distance :
   {"intent": "follow_keep_distance", "action": {"type": "Follow", "target": "Player", "keep_distance": true}}
   适用：跟随并保持距离。
5. prioritize_attack :
   {"intent": "prioritize_attack", "action": {"type": "Attack"}}
   适用：优先普通攻击/平A。

protocol_version/agent/priority/expires_on 均固定，勿改。agent 只接受 Eirin。
target 只接受 "Boss" 或 "Player"；state 只接受 "Stunned"；ability_id 只接受 "Explosion"。"""


_order_adapter = TypeAdapter(TacticalOrder)


class LLMCommandParser(CommandParser):
    """将自然语言转换为受现有 TacticalOrder Schema 限制的 JSON。"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client or create_llm_client()

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=get_llm_timeout())

    def _build_messages(self, text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"玩家指令：{text}"},
        ]

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
            response = ParseCommandResponse.model_validate(payload)
        except ValidationError as error:
            raise LLMClientError("LLM tactical response does not match TacticalOrder schema.") from error

        # 来源由服务端决定，不能相信 LLM 自行声明的来源。
        return response.model_copy(update={"source": "llm"})
