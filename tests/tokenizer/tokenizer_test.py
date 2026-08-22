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


def test_ellipsis_and_dot() -> None:
    """合法点串：1 点 → DOT；3 点 → ELLIPSIS。"""
    toks, col = _tokenize('x... .a')
    assert not col.has_errors
    assert [t.type for t in toks] == [
        RawTokenType.IDENTIFIER,
        RawTokenType.ELLIPSIS,
        RawTokenType.DOT,
        RawTokenType.IDENTIFIER,
        RawTokenType.EOF,
    ]


def test_invalid_dot_run_reported() -> None:
    """2 / >=4 个点 → tokenize.invalid_ellipsis（不静默吞点），仍按 DOT 恢复。"""
    toks, col = _tokenize('a .. b ....')
    assert [t.type for t in toks] == [
        RawTokenType.IDENTIFIER,
        RawTokenType.DOT,
        RawTokenType.IDENTIFIER,
        RawTokenType.DOT,
        RawTokenType.EOF,
    ]
    assert [d.code for d in col].count('tokenize.invalid_ellipsis') == 2


def test_bom_reported_as_warning() -> None:
    _, col = _tokenize('\ufeffa = 1\n')
    assert any(d.code == 'tokenize.bom' for d in col)
    assert all(d.severity.value == 'warning' for d in col)


def test_unicode_not_identifier_or_number() -> None:
    # 规范要求标识符 [A-Za-z_][A-Za-z0-9_]*、数字 [0-9]：Unicode 字母/数字应报 unknown_char
    toks, col = _tokenize('中 ١٢٣\n')
    assert all(d.code == 'tokenize.unknown_char' for d in col)
    assert not any(t.type is RawTokenType.IDENTIFIER for t in toks)
    assert not any(t.type is RawTokenType.INTEGER for t in toks)


def test_crlf_produces_single_newline() -> None:
    # CRLF 归一：\r 被跳过，\n 产一个 NEWLINE，不双重计数
    toks, col = _tokenize('a = 1\r\nb = 2\r\n')
    newlines = [t for t in toks if t.type is RawTokenType.NEWLINE]
    assert len(newlines) == 2
    assert not col.has_errors


def test_unclosed_bracket_reported_at_eof() -> None:
    _, col = _tokenize('a = [1, 2\n')
    assert any(d.code == 'tokenize.unterminated_bracket' for d in col)


def test_mismatched_bracket_reported() -> None:
    _, col = _tokenize('a = (1]\n')
    assert any(d.code == 'tokenize.mismatched_bracket' for d in col)


def test_unexpected_close_bracket_reported() -> None:
    _, col = _tokenize('a = 1)\n')
    assert any(d.code == 'tokenize.unexpected_close_bracket' for d in col)


def test_matched_nested_brackets_no_error() -> None:
    _, col = _tokenize('a = [1, {2: (3)}]\n')
    assert not col.has_errors


def test_nested_mismatch_reports_each_pair() -> None:
    # ([)]：两处不配对（[ 对 )、( 对 ]），均应即时报告且不崩溃
    _, col = _tokenize('a = ([)]\n')
    assert [d.code for d in col].count('tokenize.mismatched_bracket') == 2


def test_unterminated_string_reported() -> None:
    _, col = _tokenize('a = "abc\n')
    assert any(d.code == 'tokenize.unterminated_string' for d in col)


def test_import_keywords_combined() -> None:
    toks, _ = _tokenize('!env import X\n')
    assert RawTokenType.ENV_IMPORT in [t.type for t in toks]


def test_invalid_bang_reported() -> None:
    _, col = _tokenize('!bad\n')
    assert any(d.code == 'tokenize.invalid_bang' for d in col)


def test_bang_invalid_char_single_diagnostic() -> None:
    # !@：只报一次 invalid_bang，不叠加 unknown_char；!5 的 5 不再产出 INTEGER
    _, col1 = _tokenize('x = !@\n')
    assert [d.code for d in col1].count('tokenize.invalid_bang') == 1
    assert not any(d.code == 'tokenize.unknown_char' for d in col1)
    toks2, col2 = _tokenize('x = !5\n')
    assert [d.code for d in col2].count('tokenize.invalid_bang') == 1
    assert not any(t.type is RawTokenType.INTEGER for t in toks2)


def test_import_keyword_typo_corrected() -> None:
    toks, col = _tokenize('!envv import X\n')
    assert RawTokenType.ENV_IMPORT in [t.type for t in toks]
    assert any(d.code == 'tokenize.bang_corrected' for d in col)


def test_invalid_number_reported() -> None:
    _, col = _tokenize('x = +\n')
    assert any(d.code == 'tokenize.invalid_number' for d in col)


def test_signed_nan_accepted_with_warning() -> None:
    toks, col = _tokenize('x = +nan\n')
    assert any(t.type is RawTokenType.FLOAT and t.raw == 'nan' for t in toks)
    assert any(d.code == 'tokenize.signed_nan' and d.severity.value == 'warning' for d in col)


def test_invalid_number_recovers_without_illegal_token() -> None:
    # 5e+ 不再产出非法 FLOAT，补 0 恢复为合法浮点 5e+0
    toks, col = _tokenize('x = 5e+\n')
    assert any(d.code == 'tokenize.invalid_number' for d in col)
    float_tokens = [t for t in toks if t.type is RawTokenType.FLOAT]
    assert float_tokens and float_tokens[0].raw == '5e+0'
    assert not any(t.type is RawTokenType.INTEGER for t in toks)


def test_lone_plus_skipped_end_to_end() -> None:
    # 单独 + 不再产出 INTEGER '+'，直接跳过
    toks, col = _tokenize('x = +\n')
    assert any(d.code == 'tokenize.invalid_number' for d in col)
    assert not any(t.raw == '+' for t in toks)
