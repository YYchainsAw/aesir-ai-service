"""解析器抽象。

这里定义了可插拔槽位：将来 LLM 适配器会与规则解析器并存，而无需改动面向 UE
的 Schema 和 API 契约。
"""

from abc import ABC, abstractmethod

from app.schemas.tactical_order import ParseCommandResponse


class CommandParser(ABC):
    """所有命令解析后端都必须实现的契约。

    ``parse`` 把玩家的原始文本转成一个 ``ParseCommandResponse``；当其
    ``recognized`` 为真时，结果中的 ``order`` 是一个经过白名单约束的
    ``TacticalOrder``，UE 可以直接校验并执行。
    """

    @abstractmethod
    def parse(self, text: str) -> ParseCommandResponse:
        """把玩家文本指令解析为 UE 兼容的响应。"""