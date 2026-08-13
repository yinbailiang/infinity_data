"""泛型 LL(1) 流包装器 —— 对任意 AsyncIterable[T] 提供单元素预读能力。"""

from collections.abc import AsyncIterable, AsyncIterator
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
    """泛型 LL(1) 流：对任意 AsyncIterable[T] 提供单元素预读"""

    def __init__(self, source: AsyncIterable[T]) -> None:
        self._aiter: AsyncIterator[T] | None = None
        self._next: T | NoNextType | UnSetType = UnSet
        self._source: AsyncIterable[T] = source

    async def peek(self) -> T | NoNextType:
        """返回当前预读元素，首次访问时自动懒初始化。"""
        await self._ensure_buf()
        assert not isinstance(self._next, UnSetType)
        return self._next

    async def eof(self) -> bool:
        """是否已到达末尾（首次访问时自动懒初始化）。"""
        await self._ensure_buf()
        return isinstance(self._next, NoNextType)

    async def advance(self) -> T:
        """消费当前元素，步进并预读下一个。"""
        await self._ensure_buf()
        item = self._next
        if isinstance(item, NoNextType):
            raise IndexError('无法在 EOF 之后继续推进流')
        await self._pre_read()
        assert not isinstance(item, UnSetType)
        await self._on_advance(item)
        return item

    async def _ensure_buf(self) -> None:
        """懒初始化：首次访问时创建异步迭代器并预读第一个元素。"""
        if self._aiter is None:
            self._aiter = aiter(self._source)
        if self._next is UnSet:
            await self._pre_read()

    async def _pre_read(self) -> None:
        """从 _aiter 预读下一个元素到 _current。"""
        assert self._aiter is not None
        try:
            self._next = await anext(self._aiter)
        except StopAsyncIteration:
            self._next = NoNext

    async def _on_advance(self, item: T) -> None: ...
