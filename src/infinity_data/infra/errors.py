"""infd 语言公共错误基础设施。

提供所有阶段（词法分析、语法分析、语义分析、安全模型）共用的：
- 异常基类 :class:`InfinityDataError`（``source`` 统一为 ``SourceRange``）
- 错误收集器 :class:`ErrorCollector`
"""

from dataclasses import dataclass
from typing import Generic, Iterator, TypeVar

from infinity_data.infra.location import SourceRange


@dataclass
class InfinityDataError(Exception):
    """infd 语言所有错误的公共基类。

    ``source`` 统一为 :class:`SourceRange`：
    - 词法分析阶段：零宽 range（start == end，单点位置）
    - 语法/语义阶段：区间 range
    - 无源码位置的安全异常（如顶层 schema 校验失败）：None

    消息协议：子类统一重写 ``_format_message()`` 提供人类可读的描述；
    携带现成消息的安全异常在重写中直接返回它。
    """

    source: SourceRange | None

    # ── 消息协议 ──────────────────────────────────────

    @property
    def message(self) -> str:
        """错误消息"""
        return self._format_message()

    @property
    def location(self) -> str:
        """格式化的源码位置 ``file:line:col``（无位置时为 ``<unknown>``）。"""
        if self.source is None:
            return '<unknown>'
        s = self.source.start
        return f'{self.source.file.name}:{s.line}:{s.col}'

    def _format_message(self) -> str:
        """格式化错误消息，子类应重写此方法。"""
        return 'infd 错误'

    def __str__(self) -> str:
        return self.message


# ═══════════════════════════════════════════════════════════
# 公共错误收集器
# ═══════════════════════════════════════════════════════════

E = TypeVar('E', bound='InfinityDataError')
"""错误类型变量，约束为 :class:`InfinityDataError` 的子类。"""


class ErrorCollector(Generic[E]):
    """泛型错误收集器，各阶段通过继承使用。

    用法::

        collector = TokenizeErrorCollector()
        tokenizer = RawTokenizer(file, error_collector=collector)
        ...
        for err in collector:
            print(err.message)
    """

    def __init__(self) -> None:
        self._errors: list[E] = []

    # ── 写入 ──────────────────────────────────────────

    def add(self, error: E) -> None:
        """添加一个错误。"""
        self._errors.append(error)

    # ── 只读查询 ──────────────────────────────────────

    @property
    def errors(self) -> list[E]:
        """返回所有已收集错误的副本。"""
        return self._errors.copy()

    @property
    def has_errors(self) -> bool:
        """是否有已收集的错误。"""
        return len(self._errors) > 0

    # ── 容器协议 ──────────────────────────────────────

    def __iter__(self) -> Iterator[E]:
        """迭代所有已收集的错误。"""
        return iter(self._errors)
