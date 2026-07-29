"""泛型 LL(1) 流包装器 —— 对任意 AsyncIterable[T] 提供单元素预读能力。"""

from collections.abc import AsyncIterable, AsyncIterator
from typing import Generic, TypeVar

T = TypeVar("T")


class LL1Stream(Generic[T]):
    """泛型 LL(1) 流：对任意 AsyncIterable[T] 提供单元素预读。

    核心原语：
    - ``current() → T | None``  查看当前元素（不消费）
    - ``advance() → T``         消费当前元素并预读下一个
    - ``eof() → bool``          是否已到达流末尾

    所有查询方法在首次访问时自动懒初始化（创建异步迭代器并预读首元素）。
    子类可重写 ``_on_advance`` 以在消费元素时注入额外逻辑。
    """

    def __init__(self, source: AsyncIterable[T]) -> None:
        self._aiter: AsyncIterator[T] | None = None
        self._current: T | None = None
        self._exhausted: bool = False
        self._source: AsyncIterable[T] = source

    # ── 异步查询（内部懒预读）─────────────────────────────

    async def current(self) -> T | None:
        """返回当前预读元素，首次访问时自动懒初始化。"""
        await self._ensure_buf()
        return self._current

    async def eof(self) -> bool:
        """是否已到达末尾（首次访问时自动懒初始化）。"""
        await self._ensure_buf()
        return self._exhausted and self._current is None

    # ── 推进 ──────────────────────────────────────────────

    async def advance(self) -> T:
        """消费当前元素，步进并预读下一个。"""
        await self._ensure_buf()
        item = self._current
        if item is None and self._exhausted:
            raise IndexError("无法在 EOF 之后继续推进流")
        self._on_advance(item)  # type: ignore[arg-type]
        await self._pre_read()
        return item  # type: ignore[return-value]

    def _on_advance(self, item: T) -> None:
        """子类可重写：在消费元素时执行额外逻辑（如位置跟踪）。"""

    # ── 内部 ──────────────────────────────────────────────

    async def _ensure_buf(self) -> None:
        """懒初始化：首次访问时创建异步迭代器并预读第一个元素。"""
        if self._aiter is None:
            self._aiter = aiter(self._source)
        if self._current is None and not self._exhausted:
            await self._pre_read()

    async def _pre_read(self) -> None:
        """从 _aiter 预读下一个元素到 _current。"""
        assert self._aiter is not None
        try:
            self._current = await anext(self._aiter)
        except StopAsyncIteration:
            self._current = None
            self._exhausted = True
