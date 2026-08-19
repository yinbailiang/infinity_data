"""parser/token_stream.py 单元测试：TokenStream 分隔符/span/expect。"""

from pathlib import Path

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.parser.token_stream import TokenStream
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.models.tokens import EqualsToken, IdentifierToken, IntegerToken
from infinity_data.tokenizer.tokenizer import RawTokenizer


def _make(src: str):
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    col = DiagnosticCollector()
    stream = TokenStream(FinalTokenizer(RawTokenizer(file=file, error_collector=col)), col)
    return stream, col


def test_skip_newlines() -> None:
    s, _ = _make('a\n\nb\n')
    assert isinstance(s.peek(), IdentifierToken)
    s.advance()  # a
    s.skip_newlines()
    assert isinstance(s.peek(), IdentifierToken)
    assert s.peek().name == 'b'  # type: ignore[union-attr]


def test_skip_separators_returns_whether_consumed() -> None:
    s, _ = _make('[1,\n2]')
    s.advance()  # [
    assert s.skip_separators() is False  # 当前是 1，无分隔符
    s.advance()  # 1
    assert s.skip_separators() is True  # 逗号+换行被消费
    assert isinstance(s.peek(), IntegerToken)


def test_span_from() -> None:
    s, _ = _make('a = 1\n')
    first = s.peek()
    assert isinstance(first, IdentifierToken)
    s.advance()  # a
    s.advance()  # =
    rng = s.span_from(first)
    assert rng.start == first.raw.source.start
    assert rng.end.index >= rng.start.index


def test_expect_success() -> None:
    s, _ = _make('a = 1\n')
    tok = s.expect(IdentifierToken)
    assert isinstance(tok, IdentifierToken)
    assert tok.name == 'a'


def test_expect_mismatch_reports_and_recovers() -> None:
    s, col = _make('a = 1\n')
    tok = s.expect(EqualsToken)  # 当前是 Identifier a，不匹配
    assert any(d.code == 'parse.unexpected_token' for d in col)
    assert tok is not None  # 合成 token 保证调用方类型安全


def test_check() -> None:
    from infinity_data.tokenizer.models.raw_tokens import RawTokenType

    s, _ = _make('a = 1\n')
    assert not s.check(RawTokenType.EQUALS)  # 当前是 a
    s.advance()
    assert s.check(RawTokenType.EQUALS)
    assert not s.eof()


def test_eof_semantics() -> None:
    s, _ = _make('a\n')
    while not s.eof():
        s.advance()
    assert s.eof()
