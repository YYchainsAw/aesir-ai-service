"""组合端点的意图解析门面：按 ``AESIR_INTENT_BACKEND`` 选 rule / LLM，失败回退规则。

与 v0.1 的 ``app/services/parsers/command_parser`` 同一模式：LLM 输出严格
JSON 的 ``TacticalIntent``（``intent_id`` 受 ``Literal`` 白名单约束，越界
直接校验失败），任何异常（配置缺失、网络、非法输出）都回退规则解析器，
``source`` 标记实际来源（``rule`` / ``llm`` / ``rule_fallback``），供 UE 端
降级观测。
"""

from app.schemas.tactical_intent import TacticalIntent
from app.services.companion.profile_repository import (
    CompanionProfile,
    CompanionProfileError,
    get_registered_profile,
)
from app.services.llm.untrusted_input import untrusted_input_notice, wrap_untrusted_input
from app.services.tactical.intent_parser import parse_text_to_intent

try:  # 顶层 import 会让服务进程在缺 httpx 网络配置时变脆，延迟到用时再建
    from app.services.llm.client import LLMClientError
except ImportError:  # pragma: no cover - httpx 属运行时必装依赖，仅为类型安全
    class LLMClientError(RuntimeError):  # type: ignore[no-redef]
        pass


class LLMIntentError(LLMClientError):
    """LLM 意图解析链路中的任何失败。"""


_DEFAULT_GAME_NAME = "Aesir"
_DEFAULT_COMPANION_NAME = "艾莉"

# 默认 system prompt（无 profile 时回退使用）；含占位符以便动态替换。
_DEFAULT_SYSTEM_PROMPT = untrusted_input_notice() + "\n\n" + """你是一名游戏《{{GAME_NAME}}》的战术意图解析器。玩家指令都发给队友 {{COMPANION_NAME}}。
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
1. "{{COMPANION_NAME}}，快撤，保命要紧" → {"recognized":true,"intent":{"intent_id":"retreat_and_survive","target_id":"party.player","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
2. "{{COMPANION_NAME}}，等它晕了放大招" → {"recognized":true,"intent":{"intent_id":"prepare_burst_on_stun","target_id":"encounter.primary_hostile","timing":"on_condition","strength":"unspecified","resource_conservation":"normal"}}
3. "{{COMPANION_NAME}}，奶我一口" → {"recognized":true,"intent":{"intent_id":"support_heal_player","target_id":"party.player","timing":"immediate","strength":"minor","resource_conservation":"normal"}}
4. "{{COMPANION_NAME}}，给我开个盾" → {"recognized":true,"intent":{"intent_id":"support_protect_player","target_id":"party.player","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
5. "{{COMPANION_NAME}}，集火打 Boss" → {"recognized":true,"intent":{"intent_id":"focus_fire_boss","target_id":"encounter.primary_hostile","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
6. "{{COMPANION_NAME}}，把那个捡起来" → {"recognized":true,"intent":{"intent_id":"pickup_item","target_id":"","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
7. "{{COMPANION_NAME}}，我们休息一下吧" → {"recognized":true,"intent":{"intent_id":"rest_here","target_id":"","timing":"immediate","strength":"unspecified","resource_conservation":"normal"}}
指令不在白名单语义内（如闲聊）时必须返回 recognized:false，不得用近似意图替代。"""


def _companion_name_for_prompt(profile: CompanionProfile | None) -> str:
    """从 profile 取适合 prompt 使用的角色名；无 profile 时回退默认。"""
    if profile is None:
        return _DEFAULT_COMPANION_NAME
    # 优先使用 aliases 里的中文名，否则用 display_name
    for alias in profile.raw.get("identity", {}).get("aliases", []):
        if isinstance(alias, str) and any("一" <= ch <= "鿿" for ch in alias):
            return alias
    return profile.display_name


def build_system_prompt(profile: CompanionProfile | None = None) -> str:
    """根据人格包动态构造战术意图解析器的 system prompt。

    游戏名、角色名从 profile 读取；未提供 profile 时回退到默认 prompt，
    保证旧调用路径行为不变。使用字符串替换而非 ``str.format``，避免 JSON
    示例中的花括号被误解析为占位符。
    """
    game_name = profile.game_name if profile is not None else _DEFAULT_GAME_NAME
    companion_name = _companion_name_for_prompt(profile)
    return _DEFAULT_SYSTEM_PROMPT.replace(
        "{{GAME_NAME}}", game_name
    ).replace(
        "{{COMPANION_NAME}}", companion_name
    )


def parse_text_to_intent_llm(
    text: str, *, client=None, profile: CompanionProfile | None = None
) -> TacticalIntent | None:
    """LLM 解析文本 → ``TacticalIntent``；失败抛 ``LLMIntentError`` 由门面回退。

    构造时可注入共享 ``LLMClient`` 便于测试（默认按运行时配置创建）。
    ``profile`` 用于动态化 system prompt 中的游戏名/角色名；未提供时使用默认值。
    """
    if client is None:
        from app.services.llm.factory import create_llm_client

        client = create_llm_client()

    payload = client.generate_json(
        system_prompt=build_system_prompt(profile),
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


def parse_intent_with_source(
    text: str, *, companion_id: str | None = None, client=None
) -> tuple[TacticalIntent | None, str]:
    """意图解析门面：按 ``AESIR_INTENT_BACKEND`` 选后端，返回 (intent, source)。

    - backend=rule（默认）：直接走规则解析器，source="rule"。
    - backend=llm：LLM 解析成功 source="llm"；LLM 任何失败回退规则解析器，
      source="rule_fallback"。规则解析也不识别时 intent=None（调用方回复澄清）。

    ``companion_id`` 用于加载对应人格包的唤醒词与 prompt 用语；未提供时使用
    默认唤醒词与默认 system prompt。
    """
    from app.config import get_settings

    profile: CompanionProfile | None = None
    wake_words: frozenset[str] | None = None
    if companion_id is not None:
        try:
            profile = get_registered_profile(companion_id)
            wake_words = profile.wake_words
        except CompanionProfileError:
            # 未知角色仍继续：规则解析用默认唤醒词，LLM 用默认 prompt
            pass

    backend = get_settings().intent_backend
    if backend != "llm":
        return parse_text_to_intent(text, wake_words=wake_words), "rule"

    try:
        return parse_text_to_intent_llm(text, client=client, profile=profile), "llm"
    except Exception:
        return parse_text_to_intent(text, wake_words=wake_words), "rule_fallback"
