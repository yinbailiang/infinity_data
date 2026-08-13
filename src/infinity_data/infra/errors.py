"""infd 语言公共错误基础设施。

提供所有阶段（词法分析、语法分析、语义分析）共用的：
- 泛型异常基类 :class:`InfinityDataError`
- 泛型错误收集器 :class:`ErrorCollector`
"""

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

# ═══════════════════════════════════════════════════════════
# 类型变量
# ═══════════════════════════════════════════════════════════

S = TypeVar('S')
"""源码位置类型 —— 词法阶段为 ``SourceInfo``，后续阶段为 ``SourceRange``。"""

E = TypeVar('E', bound='InfinityDataError[Any]')
"""错误类型变量，约束为 :class:`InfinityDataError` 的子类。"""

# ═══════════════════════════════════════════════════════════
# 公共异常基类
# ═══════════════════════════════════════════════════════════


@dataclass
class InfinityDataError(Exception, Generic[S]):
    """infd 语言所有阶段错误的公共基类。

    泛型参数 ``S`` 为源码位置类型：
    - 词法分析阶段：``SourceInfo``（单点位置）
    - 语法/语义分析阶段：``SourceRange``（区间位置）

    子类应重写 ``_format_message()`` 以提供人类可读的中文错误描述。
    框架自动提供 ``message`` 属性和 ``__str__`` 方法。
    """

    source: S

    # ── 消息协议 ──────────────────────────────────────

    @property
    def message(self) -> str:
        """错误消息"""
        return self._format_message()

    @property
    def location(self) -> str:
        """格式化的源码位置 ``file:line:col``。

        支持两种 source 类型（duck-typing，避免 infra 依赖 tokenizer 层）：
        - ``SourceInfo``（词法阶段，单点位置）
        - ``SourceRange``（语法阶段，取起点）
        """
        point: Any = getattr(self.source, 'start', self.source)
        return f'{point.file_path}:{point.line}:{point.col}'

    def _format_message(self) -> str:
        """格式化错误消息，子类应重写此方法。"""
        return 'infd 错误'

    def __str__(self) -> str:
        return self.message


# ═══════════════════════════════════════════════════════════
# 公共错误收集器
# ═══════════════════════════════════════════════════════════


class ErrorCollector(Generic[E]):
    """泛型错误收集器，各阶段通过继承使用。

    用法::

        collector = TokenizeErrorCollector()
        tokenizer = RawTokenizer(source, error_collector=collector)
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

    def __iter__(self):
        """迭代所有已收集的错误。"""
        return iter(self._errors)
