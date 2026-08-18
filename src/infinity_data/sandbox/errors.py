"""安全异常。"""

from __future__ import annotations

from infinity_data.infra.errors import InfinityDataError
from infinity_data.infra.location import SourceRange

__all__ = ['SandboxError', 'SchemaError']


class SandboxError(InfinityDataError):
    """导入超出沙盒授权（strict 模式抛出）。"""

    _msg: str

    def __init__(self, message: str, source: SourceRange | None = None) -> None:
        super().__init__(source=source)
        self._msg = message

    def _format_message(self) -> str:
        return self._msg


class SchemaError(InfinityDataError):
    """编译产物不符合顶层 schema 约束（无具体源码位置时 source 为 None）。"""

    _msg: str

    def __init__(self, message: str, source: SourceRange | None = None) -> None:
        super().__init__(source=source)
        self._msg = message

    def _format_message(self) -> str:
        return self._msg
