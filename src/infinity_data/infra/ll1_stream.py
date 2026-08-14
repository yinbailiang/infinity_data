"""泛型 LL(1) 流包装器 —— 对任意 Iterable[T] 提供单元素预读能力。"""

from collections.abc import Iterable, Iterator
from typing import Generic, TypeVar


class UnSetType:
    def __repr__(self) -> str:
        return 'UnSet'


UnSet = UnSetType()


class NoNextType:
    def __repr__(self) -> str:
        return 'NoNext'


NoNext = NoNextType()


T = TypeVar('T')


class LL1Stream(Generic[T]):
    """泛型 LL(1) 流：对任意 Iterable[T] 提供单元素预读"""

    def __init__(self, source: Iterable[T]) -> None:
        self._iter: Iterator[T] | None = None
        self._next: T | NoNextType | UnSetType = UnSet
        self._source: Iterable[T] = source

    def peek(self) -> T | NoNextType:
        """返回当前预读元素，首次访问时自动懒初始化。"""
        self._ensure_buf()
        assert not isinstance(self._next, UnSetType)
        return self._next

    def eof(self) -> bool:
        """是否已到达末尾（首次访问时自动懒初始化）。"""
        self._ensure_buf()
        return isinstance(self._next, NoNextType)

    def advance(self) -> T:
        """消费当前元素，步进并预读下一个。"""
        self._ensure_buf()
        item = self._next
        if isinstance(item, NoNextType):
            raise IndexError('无法在 EOF 之后继续推进流')
        self._pre_read()
        assert not isinstance(item, UnSetType)
        self._on_advance(item)
        return item

    def _ensure_buf(self) -> None:
        """懒初始化：首次访问时创建迭代器并预读第一个元素。"""
        if self._iter is None:
            self._iter = iter(self._source)
        if self._next is UnSet:
            self._pre_read()

    def _pre_read(self) -> None:
        """从 _iter 预读下一个元素到 _next。"""
        assert self._iter is not None
        try:
            self._next = next(self._iter)
        except StopIteration:
            self._next = NoNext

    def _on_advance(self, item: T) -> None: ...
