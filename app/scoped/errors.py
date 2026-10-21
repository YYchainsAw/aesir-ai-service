"""作用域边界的稳定错误码，不暴露存储路径或其他玩家资料。"""

from uuid import UUID


class ScopeError(RuntimeError):
    def __init__(
        self, status_code: int, code: str, message: str, request_id: UUID | str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id

    def as_detail(self) -> dict[str, str]:
        detail = {"code": self.code, "message": self.message}
        if self.request_id is not None:
            detail["request_id"] = str(self.request_id)
        return detail
