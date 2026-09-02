"""命令解析的对外入口（facade）。

规则解析逻辑已迁到 ``parsers/rule.py``；本模块保留 ``app/api/routes.py`` 依赖的
``parse_command`` 入口，负责选择后端，并在必要时回退到规则解析器，保证服务永不
出现「无法作答」的情况。
"""

from app.config import get_parser_backend
from app.schemas.tactical_order import ParseCommandResponse
from app.services.llm.client import LLMClientError
from app.services.parsers.rule import RuleCommandParser


def parse_command(text: str) -> ParseCommandResponse:
    """把玩家文本解析为 UE 兼容的战术指令。

    根据 ``AESIR_PARSER_BACKEND``（默认 ``rule``）选择后端。只要 LLM 后端还没
    实现，它就会抛出 ``NotImplementedError``，这里捕获后回退到规则解析器，让输入
    仍能被安全解析。
    """
    if get_parser_backend() == "llm":
        try:
            from app.services.parsers.llm import LLMCommandParser

            return LLMCommandParser().parse(text)
        except LLMClientError:
            pass  # Provider 不可用或输出非法 → 回退到规则解析器。

    return RuleCommandParser().parse(text)
