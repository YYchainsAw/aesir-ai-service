"""基于 LLM 的命令解析器（第二阶段槽位，尚未接线）。

骨架阶段刻意只保留结构，不引入任何 LLM SDK 依赖。真正的集成步骤都记在
下面的 ``parse`` TODO 里：注入一个 client（OpenAI 兼容 / Ark 等）、拼接
prompt、请求结构化 JSON、按 ``TacticalOrder`` 白名单校验后返回
``ParseCommandResponse``。在此之前，facade 会回退到规则解析器。
"""

from app.schemas.tactical_order import ParseCommandResponse
from app.services.parsers.base import CommandParser


class LLMCommandParser(CommandParser):
    """基于 LLM 的解析器（第二阶段槽位）。

    TODO(第二阶段)：注入 LLM client，用玩家文本拼接 prompt，请求约束在
    ``TacticalOrder`` 白名单内的结构化 JSON，并校验为 ``ParseCommandResponse``。
    目前尚未接线。
    """

    def parse(self, text: str) -> ParseCommandResponse:
        raise NotImplementedError("AESIR_PARSER_BACKEND=llm is not implemented yet.")