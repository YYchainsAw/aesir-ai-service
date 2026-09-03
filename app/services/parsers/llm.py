"""基于 LLM 的命令解析器（复用共享的厂商无关 LLMClient，默认 DeepSeek）。

输入任意自然语言指令与 UE 能力目录 ``context``，输出契约 v0.1 的判别联合
``TacticalOrder``。实际网络调用通过 ``app.services.llm`` 的共享客户端完成；
本模块负责：构造面向 UE 的 system prompt、严格校验返回 JSON(拒绝多余字段)、
并按能力目录白名单校验 order 引用的每个 ID(防止越界)。任何失败统一抛
``LLMError``(继承共享的 ``LLMClientError``)，由 facade 捕获后回退规则解析器。
"""

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.schemas.tactical_order import (
    DEFAULT_CONTEXT,
    ParseCommandContext,
    ParseCommandResponse,
)
from app.services.llm.client import LLMClientError
from app.services.llm.factory import create_llm_client
from app.services.parsers.base import CommandParser

if TYPE_CHECKING:
    from app.services.llm.client import LLMClient


class LLMError(LLMClientError):
    """LLM 解析链路中的任何失败（配置缺失、网络、非法输出、目录越界）。"""


def _build_system_prompt(context: ParseCommandContext) -> str:
    """把 UE 能力目录的稳定 ID 喂给 LLM，并给出契约 v0.1 输出结构。"""
    agents = "\n".join(
        f"- agent {a.id!r} 可用技能: " + ", ".join(repr(x) for x in a.ability_ids)
        for a in context.agents
    )
    selectors = ", ".join(repr(x) for x in context.target_selectors)
    states = ", ".join(repr(x) for x in context.state_tags)

    return (
        "你是一名游戏《Aesir》的战术指令解析器。玩家指令都发给队友。"
        "请把中文自然语言指令解析为受限 JSON，只输出 JSON，不要任何解释、代码块或说明。\n\n"
        "能力目录（只许使用这里的 ID，禁止发明、禁止用中文显示名）：\n"
        f"agents:\n{agents}\n"
        f"target_selectors: [{selectors}]\n"
        f"state_tags: [{states}]\n\n"
        "输出对象结构：\n"
        '{"recognized":true,"order":{...},"message":"..."} 或无法识别时 '
        '{"recognized":false,"order":null,"message":"..."}\n'
        "order 结构（按 intent 判别）：\n"
        '通用字段：order_id 由服务端生成、不用输出；agent_id 取自目录；priority 为 0..100 整数；'
        'expires 固定 {"type":"encounter_end"}。\n'
        "1. conditional_cast（条件满足时施法一次）："
        'when={"type":"state_entered","subject":"<目标选择器>","tag":"<状态tag>"}，'
        'then={"type":"cast_ability","ability_id":"<技能ID>","target":"<目标选择器> 或 {"ref":"when.subject"}"}。\n'
        "2. hold_ability：when=null，"
        'then={"type":"hold_ability","ability_id":"<技能ID>","active":true}。\n'
        "3. prioritize_attack：when=null，then={\"type\":\"set_priority\",\"mode\":\"basic_attack_first\"}。\n"
        "4. follow_keep_distance：when=null，"
        'then={"type":"follow","target":"party.player","keep_distance":true}。\n'
        "5. retreat：when=null，then={\"type\":\"retreat\"}。\n\n"
        "golden 示例（用上目录的 ID 替换占位；message 用简洁中文）：\n"
        '1. conditional_cast → {"recognized":true,"message":"好，等Boss眩晕时释放爆裂魔法。","order":{"agent_id":"companion.eirin","intent":"conditional_cast","priority":80,"when":{"type":"state_entered","subject":"encounter.primary_hostile","tag":"state.stunned"},"then":{"type":"cast_ability","ability_id":"ability.eirin.explosion","target":{"ref":"when.subject"}}}}；\n'
        '2. hold_ability → {"recognized":true,"message":"明白，保留爆裂魔法。","order":{"agent_id":"companion.eirin","intent":"hold_ability","priority":60,"when":null,"then":{"type":"hold_ability","ability_id":"ability.eirin.explosion","active":true}}}；\n'
        '3. prioritize_attack → {"recognized":true,"message":"了解，优先普攻。","order":{"agent_id":"companion.eirin","intent":"prioritize_attack","priority":50,"when":null,"then":{"type":"set_priority","mode":"basic_attack_first"}}}；\n'
        '4. follow_keep_distance → {"recognized":true,"message":"好，跟上你并保持距离。","order":{"agent_id":"companion.eirin","intent":"follow_keep_distance","priority":40,"when":null,"then":{"type":"follow","target":"party.player","keep_distance":true}}}；\n'
        '5. retreat → {"recognized":true,"message":"知道了，先撤，优先保命。","order":{"agent_id":"companion.eirin","intent":"retreat","priority":90,"when":null,"then":{"type":"retreat"}}}\n'
        "只有一条要求必须严格遵守：order 里引用的每个 ID 都必须来自上面的能力目录，"
        "否则这次解析无效。语气要符合战术指挥。"
    )


def _validate_catalog(context: ParseCommandContext, order: Any) -> None:
    """校验 order 引用的 ID 是否都落在目录内；越界抛 LLMError。"""
    agent_by_id = {a.id: a for a in context.agents}
    selectors = set(context.target_selectors)
    states = set(context.state_tags)

    agent = agent_by_id.get(order.agent_id)
    if agent is None:
        raise LLMError(f"Agent {order.agent_id!r} not in catalog.")

    then = order.then
    # 有 ability_id 的动作，必须属于该 agent 的能力目录
    if getattr(then, "ability_id", None) is not None:
        if then.ability_id not in agent.ability_ids:
            raise LLMError(f"Ability {then.ability_id!r} not in agent catalog.")

    if order.when is not None:
        if order.when.subject not in selectors:
            raise LLMError(f"when.subject {order.when.subject!r} not in catalog.")
        if order.when.tag not in states:
            raise LLMError(f"when.tag {order.when.tag!r} not in catalog.")

    # then.target 可能是选择器字符串或 TargetRef；字符串必须命中选择器
    target = getattr(then, "target", None)
    if isinstance(target, str) and target not in selectors:
        raise LLMError(f"then.target {target!r} not in catalog.")


class LLMCommandParser(CommandParser):
    """基于 LLM 的解析器。构造时可注入共享 ``LLMClient`` 便于测试。"""

    def __init__(self, client=None) -> None:
        # 业务层只依赖 LLMClient 协议；缺省用运行时配置创建。
        from app.services.llm.client import LLMClient

        if client is None:
            self._client: LLMClient = create_llm_client()
        else:
            self._client = client

    def parse(
        self,
        text: str,
        context: ParseCommandContext = DEFAULT_CONTEXT,
        request_id=None,
    ) -> ParseCommandResponse:
        payload = self._client.generate_json(
            system_prompt=_build_system_prompt(context),
            user_prompt=f"玩家指令：{text}",
            temperature=0.0,
        )
        try:
            response = ParseCommandResponse.model_validate(payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise LLMError(f"LLM output failed validation: {exc}") from exc

        if response.order is not None:
            _validate_catalog(context, response.order)

        # 来源由服务端决定，不能轻信 LLM 自报；request_id 回显调用方。
        return response.model_copy(update={"source": "llm", "request_id": request_id})