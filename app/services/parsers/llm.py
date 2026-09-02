"""基于 LLM 的命令解析器（OpenAI 兼容 Chat Completions API，默认 DeepSeek）。

输入任意自然语言指令，输出被白名单约束的 ``TacticalOrder``。所有网络/JSON/
Pydantic 校验失败统一转成 ``LLMError``，由 facade 捕获后回退到规则解析器，
保证 UE 永不收到不合法的 order。
"""

import json

import httpx
from pydantic import TypeAdapter

from app.config import get_llm_api_key, get_llm_base_url, get_llm_model, get_llm_timeout
from app.schemas.tactical_order import ParseCommandResponse, TacticalOrder
from app.services.parsers.base import CommandParser


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
    """基于 LLM 的解析器。构造时可注入 httpx.Client 便于测试。

    TODO(后续可选)：异步化、流式、多轮对话、fine-tune。当前保持同步，由
    FastAPI 线程池承载，与现有同步路由一致。
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=get_llm_timeout())

    def _build_messages(self, text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"玩家指令：{text}"},
        ]

    def parse(self, text: str) -> ParseCommandResponse:
        api_key = get_llm_api_key()
        if not api_key:
            raise LLMNotConfiguredError(
                "LLM_API_KEY is not set; refusing to call the LLM API."
            )

        base_url = get_llm_base_url().rstrip("/")
        try:
            resp = self._client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": get_llm_model(),
                    "messages": self._build_messages(text),
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        return self._parse_response_content(content)

    def _parse_response_content(self, content: str) -> ParseCommandResponse:
        """把 LLM 返回的 JSON 字符串校验为 ParseCommandResponse。"""
        try:
            raw = json.loads(content)
            if not isinstance(raw, dict):
                raise ValueError("LLM response is not a JSON object.")
            if raw.get("recognized") is False:
                return ParseCommandResponse(
                    recognized=False,
                    order=None,
                    message=str(raw.get("message") or "Command not recognized."),
                )
            order_dict = raw.get("order")
            if not isinstance(order_dict, dict):
                raise ValueError("LLM response is missing a valid 'order' object.")
            order = _order_adapter.validate_python(order_dict)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM output failed validation: {exc}") from exc

        return ParseCommandResponse(
            recognized=True,
            order=order,
            message="Command recognized by the LLM parser.",
        )