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
    EofToken,
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
        """构造 Token 流：source + 共享诊断收集器（错误恢复用）。"""
        super().__init__(source)
        self._errors: DiagnosticCollector = error_collector
        self._last: Token | None = None
        self._nesting_depth: int = 0

    # ── 嵌套深度（防 RecursionError）──────────────────

    @property
    def nesting_depth(self) -> int:
        """当前嵌套深度（递归下降容器进入层级）。"""
        return self._nesting_depth

    def enter_nested(self) -> int:
        """进入一层嵌套（dict/array/模板调用/约束调用），返回递增后深度。"""
        self._nesting_depth += 1
        return self._nesting_depth

    def exit_nested(self) -> None:
        """退出一层嵌套。"""
        self._nesting_depth -= 1

    # ── LL1Stream 钩子 ────────────────────────────────────

    def _on_advance(self, item: Token) -> None:
        """消费每个 token 时记录，用于 range 追踪。

        换行 token 不计入 ``_last``——span 终点始终落在最后一个内容 token，
        使节点 source 不吞入尾部换行（如 file 导入循环预读换行判断后续项时）。
        """
        if not isinstance(item, NewlineToken):
            self._last = item

    def check(self, expect: RawTokenType) -> bool:
        """当前 token 是否匹配期望类型（物理耗尽 → False）。"""
        token = self.peek()
        if isinstance(token, NoNextType):
            return False
        return token.raw.type == expect

    def eof(self) -> bool:
        """结束判定：当前 token 为 EofToken，或流已物理耗尽（哨兵被消费后）。

        EofToken 是 FinalTokenizer 产出的哨兵 token；基类 :class:`LL1Stream` 的
        ``eof()`` 只认物理耗尽（哨兵被消费后才为 True），此处统一为「哨兵即结束」
        ——解析循环无需再区分 ``check(EOF)`` 与 ``eof()``。
        """
        return isinstance(self.peek(), (EofToken, NoNextType))

    # ── 跳过 ───────────────────────────────────────

    def skip_newlines(self) -> None:
        """跳过连续的换行"""
        while not self.eof() and isinstance(self.peek(), NewlineToken):
            self.advance()

    def skip_separators(self) -> bool:
        """跳过逗号和换行（元素分隔符）。

        Returns:
            是否消费了至少一个分隔符——区分「有分隔符」与「无分隔符」：
            元素之间必须显式分隔，空格不构成分隔符。
        """
        saw = False
        while not self.eof() and isinstance(self.peek(), (CommaToken, NewlineToken)):
            self.advance()
            saw = True
        return saw

    # ── Range 追踪 ────────────────────────────────────────

    def span_from(self, first: Token | NoNextType | None) -> SourceRange:
        """计算从 first 到当前最后消费 token 的 SourceRange。"""
        if isinstance(first, NoNextType) or first is None:
            first = self._last
        if isinstance(first, NoNextType) or first is None:
            return SourceRange.empty()
        last = self._last if self._last else first
        start = first.raw.source.start
        end = last.raw.source.end
        if start.index > end.index:
            # first 是未消费的 peek（位于已消费区之后，如 EOF 处）→ 退化为 first 单点
            return SourceRange(file=first.raw.source.file, start=start, end=start)
        return SourceRange(file=first.raw.source.file, start=start, end=end)

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
            rng = self._eof_span()
            self._errors.add(diag('parse.unexpected_token', {'expected': token_cls.__name__, 'actual': 'EOF'}, rng))
            return self._synthetic(token_cls, source=rng)
        if not isinstance(tok, token_cls):
            self._errors.add(
                diag(
                    'parse.unexpected_token',
                    {'expected': token_cls.__name__, 'actual': tok.raw.type.name},
                    tok.raw.source,
                )
            )
            self.advance()
            return self._synthetic(token_cls, source=tok.raw.source)
        self.advance()
        return tok

    def _synthetic(self, token_cls: type[_TToken], *, source: SourceRange | None = None) -> _TToken:
        """构造合成 token（错误恢复用）。

        source 缺省时定位到最后消费 token 的末尾单点（近似文件末尾）。
        """
        rng = source or self._eof_span()
        raw = RawToken(type=RawTokenType.EOF, raw='', source=rng)
        return token_cls(raw=raw)

    def _eof_span(self) -> SourceRange:
        """EOF 处定位：最后消费 token 的末尾单点（近似文件末尾）；未消费任何 token 则 empty。"""
        if self._last is None:
            return SourceRange.empty()
        end = self._last.raw.source.end
        return SourceRange(file=self._last.raw.source.file, start=end, end=end)
