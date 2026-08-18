"""LL(1) Token 流包装器，继承 LL1Stream[Token]，自动追踪 source range。

全链路流式：CharStream → RawToken → Token → AST。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.ll1_stream import LL1Stream, NoNextType
from infinity_data.parser.diagnostics import diag
from infinity_data.tokenizer.models.raw_tokens import (
    RawToken,
    RawTokenType,
    SourceRange,
)
from infinity_data.tokenizer.models.tokens import (
    CommaToken,
    NewlineToken,
    Token,
)

_TToken = TypeVar('_TToken', bound=Token)


class TokenStream(LL1Stream[Token]):
    """LL(1) Token 流，继承 LL1Stream[Token]"""

    def __init__(
        self,
        source: Iterable[Token],
        error_collector: DiagnosticCollector,
    ) -> None:
        super().__init__(source)
        self._errors: DiagnosticCollector = error_collector
        self._last: Token | None = None

    # ── LL1Stream 钩子 ────────────────────────────────────

    def _on_advance(self, item: Token) -> None:
        """消费每个 token 时记录，用于 range 追踪。"""
        self._last = item

    def check(self, expect: RawTokenType) -> bool:
        token = self.peek()
        if isinstance(token, NoNextType):
            return False
        return token.raw.type == expect

    # ── 跳过 ───────────────────────────────────────

    def skip_newlines(self) -> None:
        """跳过连续的换行"""
        while not self.eof() and isinstance(self.peek(), NewlineToken):
            self.advance()

    def skip_separators(self) -> None:
        """跳过逗号和换行"""
        while not self.eof() and isinstance(self.peek(), (CommaToken, NewlineToken)):
            self.advance()

    # ── Range 追踪 ────────────────────────────────────────

    def span_from(self, first: Token | NoNextType | None) -> SourceRange:
        """计算从 first 到当前最后消费 token 的 SourceRange。"""
        if isinstance(first, NoNextType) or first is None:
            first = self._last
        if isinstance(first, NoNextType) or first is None:
            return SourceRange.empty()
        last = self._last if self._last else first
        return SourceRange(file=first.raw.source.file, start=first.raw.source.start, end=last.raw.source.end)

    @staticmethod
    def single_span(token: Token) -> SourceRange:
        """为单个 token 创建 SourceRange。"""
        return SourceRange(file=token.raw.source.file, start=token.raw.source.start, end=token.raw.source.end)

    # ── 期望 / 错误恢复 ─────────────────────────────

    def expect(self, token_cls: type[_TToken]) -> _TToken:
        """期望当前 token 为指定类型，否则收集错误并插入合成 token。

        错误恢复策略：记录 UnexpectedTokenError → 消费意外 token → 返回合成 token。
        合成 token 保证调用方拿到类型安全的对象，解析器始终前进，避免级联崩溃。
        """
        tok = self.peek()
        if isinstance(tok, NoNextType):
            rng = self.span_from(None)
            self._errors.add(diag('parse.unexpected_token', {'expected': token_cls.__name__, 'actual': 'EOF'}, rng))
            return self._synthetic(token_cls, source=rng)
        if not isinstance(tok, token_cls):
            self._errors.add(
                diag('parse.unexpected_token', {'expected': token_cls.__name__, 'actual': tok.raw.type.name}, tok.raw.source)
            )
            self.advance()
            return self._synthetic(token_cls, source=tok.raw.source)
        self.advance()
        return tok

    def _synthetic(self, token_cls: type[_TToken], *, source: SourceRange | None = None) -> _TToken:
        """构造合成 token（错误恢复用）。"""
        rng = source or self.span_from(None)
        raw = RawToken(type=RawTokenType.EOF, raw='', source=rng)
        return token_cls(raw=raw)
