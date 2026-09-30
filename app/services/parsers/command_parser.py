"""命令解析的对外入口（facade）。

规则解析与 LLM 解析都要求能力目录与 request_id；本模块保留路由依赖的
``parse_command`` 入口，负责选择后端，并在必要时回退到规则解析器，保证
服务永不出现「无法作答」的情况。成功解析出 order 后，会附带由人设配置
生成的 ``companion_reply``（队友确认回应）。
"""

from uuid import UUID

from app.config import get_settings
from app.schemas.tactical_order import DEFAULT_CONTEXT, ParseCommandContext, ParseCommandResponse
from app.services.parsers.rule import RuleCommandParser
from app.services.tactical.acknowledgement_service import create_tactical_acknowledgement


def _attach_acknowledgement(
    response: ParseCommandResponse, *, companion_id: str
) -> ParseCommandResponse:
    """为已识别的 order 挂上队友确认回应；未识别则原样返回。"""
    if response.order is None:
        return response
    acknowledgement = create_tactical_acknowledgement(
        response.order.intent, companion_id=companion_id
    )
    return response.model_copy(update={"companion_reply": acknowledgement})


def _primary_companion_id(context: ParseCommandContext) -> str:
    """从解析上下文取主队友 ID；无 agent 时回退默认 Alice。"""
    if context.agents:
        return context.agents[0].id
    return "companion.alice"


def parse_command(
    text: str,
    context: ParseCommandContext = DEFAULT_CONTEXT,
    request_id: UUID | None = None,
) -> ParseCommandResponse:
    """把玩家文本解析为 UE 兼容的战术指令。

    根据 ``AESIR_PARSER_BACKEND``（默认 ``rule``）选择后端。只要 LLM 后端还没
    实现或调用失败，它就会抛出异常，这里捕获后回退到规则解析器，让输入仍能
    被安全解析。
    """
    companion_id = _primary_companion_id(context)
    response: ParseCommandResponse
    if get_settings().parser_backend == "llm":
        try:
            from app.services.parsers.llm import LLMCommandParser

            llm_response = LLMCommandParser().parse(text, context, request_id)
            if llm_response.recognized:
                return _attach_acknowledgement(
                    llm_response.model_copy(update={"source": "llm"}),
                    companion_id=companion_id,
                )
            # LLM 明确不确定(recognized:false) → 让规则解析器最终兜底
        except Exception:
            pass  # LLM 配置缺失 / 网络 / 校验失败 → 回退到规则解析器，保证不崩。

        response = RuleCommandParser().parse(text, context, request_id).model_copy(
            update={"source": "rule_fallback"}
        )
    else:
        response = RuleCommandParser().parse(text, context, request_id)

    return _attach_acknowledgement(response, companion_id=companion_id)