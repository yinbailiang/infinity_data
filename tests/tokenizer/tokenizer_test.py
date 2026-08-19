"""tokenizer/tokenizer.py 单元测试：RawTokenizer 词法规则与容错。"""

from pathlib import Path

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.tokenizer.models.raw_tokens import RawTokenType
from infinity_data.tokenizer.tokenizer import RawTokenizer


def _tokenize(src: str):
    col = DiagnosticCollector()
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    tokens = list(RawTokenizer(file=file, error_collector=col))
    return tokens, col


def test_basic_field_tokens() -> None:
    toks, col = _tokenize('a = 1\n')
    assert not col.has_errors
    assert [t.type for t in toks] == [
        RawTokenType.IDENTIFIER,
        RawTokenType.EQUALS,
        RawTokenType.INTEGER,
        RawTokenType.NEWLINE,
        RawTokenType.EOF,
    ]


def test_keywords_mapped() -> None:
    toks, _ = _tokenize('null noexist true false nan')
    assert [t.type for t in toks] == [
        RawTokenType.NULL,
        RawTokenType.NOEXIST,
        RawTokenType.BOOL,
        RawTokenType.BOOL,
        RawTokenType.FLOAT,
        RawTokenType.EOF,
    ]


def test_unknown_char_reported() -> None:
    _, col = _tokenize('a = 1 @\n')
    assert any(d.code == 'tokenize.unknown_char' for d in col)


def test_bom_reported_as_warning() -> None:
    _, col = _tokenize('\ufeffa = 1\n')
    assert any(d.code == 'tokenize.bom' for d in col)
    assert all(d.severity.value == 'warning' for d in col)


def test_unclosed_bracket_reported_at_eof() -> None:
    _, col = _tokenize('a = [1, 2\n')
    assert any(d.code == 'tokenize.unterminated_bracket' for d in col)


def test_unterminated_string_reported() -> None:
    _, col = _tokenize('a = "abc\n')
    assert any(d.code == 'tokenize.unterminated_string' for d in col)


def test_import_keywords_combined() -> None:
    toks, _ = _tokenize('!env import X\n')
    assert RawTokenType.ENV_IMPORT in [t.type for t in toks]


def test_invalid_bang_reported() -> None:
    _, col = _tokenize('!bad\n')
    assert any(d.code == 'tokenize.invalid_bang' for d in col)


def test_invalid_number_reported() -> None:
    _, col = _tokenize('x = +\n')
    assert any(d.code == 'tokenize.invalid_number' for d in col)
