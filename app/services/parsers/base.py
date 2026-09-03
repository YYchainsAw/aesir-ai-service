"""解析器抽象。

可插拔槽位：将来 LLM 适配器与规则解析器并存，而无需改动面向 UE 的
Schema 和 API 契约。所有解析器现在除文本外，还需接收 UE 能力目录
``context`` 与用于跨端关联的 ``request_id``。
"""

from abc import ABC, abstractmethod
from uuid import UUID, uuid4

from app.schemas.tactical_order import DEFAULT_CONTEXT, ParseCommandContext, ParseCommandResponse


class CommandParser(ABC):
    """所有命令解析后端都必须实现的契约。

    ``parse`` 把玩家文本转成一个 ``ParseCommandResponse``；当其 ``recognized``
    为真时，``order`` 是一个通过能力目录白名单约束的 ``TacticalOrder``，UE
    可直接校验并执行。能力目录缺省使用 ``DEFAULT_CONTEXT`` 以兼容遗留调用。
    """

    @abstractmethod
    def parse(
        self,
        text: str,
        context: ParseCommandContext = DEFAULT_CONTEXT,
        request_id: UUID | None = None,
    ) -> ParseCommandResponse:
        """把玩家文本指令解析为 UE 兼容的响应。"""