"""异步 LL(1) Token 流包装器，继承 LL1Stream[Token]，自动追踪 source range。

全链路流式：CharStream → RawToken → Token → AST。
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import TypeVar

from infinity_data.infra.ll1_stream import LL1Stream
from infinity_data.parser.errors import ParseErrorCollector, UnexpectedTokenError
from infinity_data.tokenizer.models.raw_tokens import RawTokenType, SourceRange
from infinity_data.tokenizer.models.tokens import (
    CommaToken,
    NewlineToken,
    Token,
)

_TToken = TypeVar("_TToken", bound=Token)


class TokenStream(LL1Stream[Token]):
    """异步 LL(1) Token 流，继承 LL1Stream[Token]。

    在 LL1Stream 基础上增加了：
    - 自动 range 追踪（通过 _on_advance 钩子）
    - 同步 peek / check / is_done（利用预读的 _current）
    - skip_newlines / skip_separators
    - expect（类型化错误收集 + 恢复）

    用法:
        stream = TokenStream(token_source, error_collector)
        await stream.current()          # 懒初始化，预读第一个 token
        while not stream.is_done():
            tok = stream.peek()         # 同步，无需 await
            ...
            await stream.advance()      # 异步消费
    """

    def __init__(
        self,
        source: AsyncIterable[Token],
        error_collector: ParseErrorCollector,
    ) -> None:
        super().__init__(source)
        self._errors: ParseErrorCollector = error_collector
        self._last: Token | None = None

    # ── LL1Stream 钩子 ────────────────────────────────────

    def _on_advance(self, item: Token) -> None:
        """消费每个 token 时记录，用于 range 追踪。"""
        self._last = item

    # ── 同步查询（利用 LL1Stream 预读的 _current）─────────

    def peek(self) -> Token:
        """同步查看当前 token（需已调用过 current() 初始化）。"""
        assert self._current is not None, "请先 await stream.current() 初始化流"
        return self._current

    def check(self, token_type: RawTokenType) -> bool:
        """检查当前 token 类型（同步）。"""
        if self._exhausted:
            return token_type is RawTokenType.EOF
        return self.peek().raw.type is token_type

    def is_done(self) -> bool:
        """是否已到达流末尾（同步）。"""
        return self._exhausted

    # ── 跳过（异步）───────────────────────────────────────

    async def skip_newlines(self) -> None:
        """跳过连续的换行 token。"""
        while not self.is_done() and isinstance(self.peek(), NewlineToken):
            await self.advance()

    async def skip_separators(self) -> None:
        """跳过逗号和换行（两者在 .infd 中等价）。"""
        while isinstance(self.peek(), (CommaToken, NewlineToken)):
            await self.advance()

    # ── Range 追踪 ────────────────────────────────────────

    def span_from(self, first: Token) -> SourceRange:
        """计算从 first 到当前最后消费 token 的 SourceRange。"""
        last = self._last if self._last else first
        return SourceRange(start=first.raw.source.start, end=last.raw.source.end)

    @staticmethod
    def single_span(tok: Token) -> SourceRange:
        """单个 token 的 SourceRange。"""
        return tok.raw.source

    # ── 期望 / 错误恢复（异步）─────────────────────────────

    async def expect(self, token_cls: type[_TToken]) -> _TToken:
        """期望当前 token 为指定类型，否则收集错误并尝试恢复。

        错误恢复策略：收集 UnexpectedTokenError → 跳过意外 token → 返回当前位置 token。
        """
        tok = self.peek()
        if not isinstance(tok, token_cls):
            self._errors.add(UnexpectedTokenError(
                source=self.single_span(tok),
                expected=token_cls.__name__,
                actual=tok.raw.type.name,
            ))
            await self.advance()
            if self.is_done():
                return tok  # type: ignore[return-value]
            return self.peek()  # type: ignore[return-value]
        await self.advance()
        return tok
