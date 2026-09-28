"""组合端点的意图解析门面：按 ``AESIR_INTENT_BACKEND`` 选 rule / LLM，失败回退规则。

与 v0.1 的 ``app/services/parsers/command_parser`` 同一模式：LLM 输出严格
JSON 的 ``TacticalIntent``（``intent_id`` 受 ``Literal`` 白名单约束，越界
直接校验失败），任何异常（配置缺失、网络、非法输出）都回退规则解析器，
``source`` 标记实际来源（``rule`` / ``llm`` / ``rule_fallback``），供 UE 端
降级观测。
"""

from app.schemas.tactical_intent import TacticalIntent
from app.services.llm.untrusted_input import untrusted_input_notice, wrap_untrusted_input
from app.services.tactical.intent_parser import parse_text_to_intent

try:  # 顶层 import 会让服务进程在缺 httpx 网络配置时变脆，延迟到用时再建
    from app.services.llm.client import LLMClientError
except ImportError:  # pragma: no cover - httpx 属运行时必装依赖，仅为类型安全
    class LLMClientError(RuntimeError):  # type: ignore[no-redef]
        pass


class LLMIntentError(LLMClientError):
    """LLM 意图解析链路中的任何失败。"""


_SYSTEM_PROMPT = untrusted_input_notice() + "\n\n" + """你是一名游戏《Aesir》的战术意图解析器。玩家指令都发给队友艾莉。
请把中文自然语言指令解析为受限 JSON，只输出 JSON，不要任何解释、代码块或说明。

intent_id 只能取以下白名单值（禁止发明），按域分两组：
战斗域（7 个，v0.2 既有）：
- support_heal_player     治疗/回血玩家（target_id="party.player"）
- support_protect_player   给玩家护盾/保命（target_id="party.player"）
- burst_boss               立即对 Boss 爆发输出（target_id="encounter.primary_hostile"）
- prepare_burst_on_stun    等 Boss 眩晕再爆发（timing="on_condition"）
- focus_fire_boss          集火 Boss（target_id="encounter.primary_hostile"）
- retreat_and_survive      撤退保命（target_id="party.player"）
- follow_player            跟随玩家（target_id="party.player"）
非战斗域（4 个）：
- inspect_interactable     查看/留意某个物件（target_id 留空）
- pickup_item              拾取物品（target_id 留空）
- rest_here                原地休整（target_id 留空）
- wait_here                原地等待玩家（target_id="party.player"）

输出对象结构（无法识别玩家意图时 recognized 为 false）：
{"recognized":true,"intent":{"intent_id":"...","target_id":"...","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
或 {"recognized":false,"intent":null}

字段约束：timing ∈ immediate/on_condition/when_possible；strength ∈ unspecified/minor/major；
resource_conservation ∈ normal/conservative/aggressive。治疗指令提到"强效/大/满血"时 strength="major"，
"小/快速/一口"时 strength="minor"。求稳/resource 相关的措辞（如"省着点"）→ conservative；
"别留手/全力"→ aggressive。

golden 示例：
1. "艾莉，快撤，保命要紧" → {"recognized":true,"intent":{"intent_id":"retreat_and_survive","target_id":"party.player","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
2. "艾莉，等它晕了放大招" → {"recognized":true,"intent":{"intent_id":"prepare_burst_on_stun","target_id":"encounter.primary_hostile","timing":"on_condition","strength":"unspecified","resource_conservation":"normal"}}
3. "艾莉，奶我一口" → {"recognized":true,"intent":{"intent_id":"support_heal_player","target_id":"party.player","timing":"immediate","strength":"minor","resource_conservation":"normal"}}
4. "艾莉，给我开个盾" → {"recognized":true,"intent":{"intent_id":"support_protect_player","target_id":"party.player","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
5. "艾莉，集火打 Boss" → {"recognized":true,"intent":{"intent_id":"focus_fire_boss","target_id":"encounter.primary_hostile","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
6. "艾莉，把那个捡起来" → {"recognized":true,"intent":{"intent_id":"pickup_item","target_id":"","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
7. "艾莉，我们休息一下吧" → {"recognized":true,"intent":{"intent_id":"rest_here","target_id":"","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
指令不在白名单语义内（如闲聊）时必须返回 recognized:false，不得用近似意图替代。"""


def parse_text_to_intent_llm(text: str, client=None) -> TacticalIntent | None:
    """LLM 解析文本 → ``TacticalIntent``；失败抛 ``LLMIntentError`` 由门面回退。

    构造时可注入共享 ``LLMClient`` 便于测试（默认按运行时配置创建）。
    """
    if client is None:
        from app.services.llm.factory import create_llm_client

        client = create_llm_client()

    payload = client.generate_json(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=wrap_untrusted_input(text, role="玩家指令"),
        temperature=0.0,
    )

    if not isinstance(payload, dict) or "intent" not in payload:
        raise LLMIntentError("LLM output missing 'intent' field.")
    if not payload.get("recognized", True):
        return None

    intent_payload = payload["intent"]
    if not isinstance(intent_payload, dict):
        raise LLMIntentError("LLM 'intent' must be an object.")
    # strength / resource_conservation 平铺进 preferences，再交给 TacticalIntent
    # 的 Literal 白名单校验——越界 intent_id 或枚举值在这里直接失败。
    preferences = {
        "strength": intent_payload.get("strength", "unspecified"),
        "resource_conservation": intent_payload.get("resource_conservation", "normal"),
    }
    try:
        return TacticalIntent(
            intent_id=intent_payload.get("intent_id", ""),
            target_id=intent_payload.get("target_id", ""),
            timing=intent_payload.get("timing", "immediate"),
            preferences=preferences,
            normalized_text=text,
            parse_confidence=0.85,
        )
    except Exception as exc:  # ValidationError 等，统一交给门面回退
        raise LLMIntentError(f"LLM output failed validation: {exc}") from exc


def parse_intent_with_source(text: str, *, client=None) -> tuple[TacticalIntent | None, str]:
    """意图解析门面：按 ``AESIR_INTENT_BACKEND`` 选后端，返回 (intent, source)。

    - backend=rule（默认）：直接走规则解析器，source="rule"。
    - backend=llm：LLM 解析成功 source="llm"；LLM 任何失败回退规则解析器，
      source="rule_fallback"。规则解析也不识别时 intent=None（调用方回复澄清）。
    """
    from app.config import get_settings

    backend = get_settings().intent_backend
    if backend != "llm":
        return parse_text_to_intent(text), "rule"

    try:
        return parse_text_to_intent_llm(text, client=client), "llm"
    except Exception:
        return parse_text_to_intent(text), "rule_fallback"
