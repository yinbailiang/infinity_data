"""tokenizer/tokenizer.py 静态方法直接单测。

方法已纯化为 ``@staticmethod``，测试无需经过 ``RawTokenizer`` 实例，
直接构造依赖（CharStream + DiagnosticCollector + MemFile）逐个传入即可，
零 mock 框架。
"""

# pyright: reportPrivateUsage=false
# 白盒单测：有意直接访问受保护静态方法，故关闭该文件的私有成员使用检查。

import json
from pathlib import Path

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.infra.location import SourceInfo, SourceRange
from infinity_data.tokenizer.char_stream import CharStream
from infinity_data.tokenizer.models.raw_tokens import RawToken, RawTokenType
from infinity_data.tokenizer.tokenizer import RawTokenizer


def _file(content: str = '') -> MemFile:
    return MemFile(name='t.infd', root_path=Path('.'), content=content)


def _tok(raw: str, file: MemFile, index: int = 0) -> RawToken:
    info = SourceInfo(line=1, col=index + 1, index=index)
    return RawToken(type=RawTokenType.IDENTIFIER, raw=raw, source=SourceRange.at(file, info))


# ── _detect_bom ──────────────────────────────────────


def test_detect_bom_reports_and_skips() -> None:
    file = _file('\ufeffa')
    stream = CharStream('\ufeffa')
    col = DiagnosticCollector()
    RawTokenizer._detect_bom(stream, col, file)
    assert any(d.code == 'tokenize.bom' and d.severity.value == 'warning' for d in col)
    assert stream.peek() == 'a'


def test_detect_bom_absent_noop() -> None:
    file = _file('a')
    stream = CharStream('a')
    col = DiagnosticCollector()
    RawTokenizer._detect_bom(stream, col, file)
    assert not col.has_errors
    assert stream.peek() == 'a'


# ── _make_token ──────────────────────────────────────


def test_make_token_spans_start_to_current() -> None:
    file = _file('ab')
    stream = CharStream('ab')
    start = stream.info()
    stream.advance()  # 消费 'a'
    tok = RawTokenizer._make_token(RawTokenType.IDENTIFIER, 'a', start, stream, file)
    assert tok.type is RawTokenType.IDENTIFIER
    assert tok.raw == 'a'
    assert tok.source.file is file
    assert tok.source.start.index == 0
    assert tok.source.end.index == 1


# ── 空白与注释 ───────────────────────────────────────


def test_skip_whitespace_and_single_line_comment() -> None:
    file = _file('  # comment\nx')
    stream = CharStream('  # comment\nx')
    col = DiagnosticCollector()
    RawTokenizer._skip_whitespace_and_comments(stream, col, file)
    assert stream.peek() == '\n'  # 换行保留为 NEWLINE token
    assert not col.has_errors


def test_skip_multiline_comment() -> None:
    file = _file('#+a\nb#-x')
    stream = CharStream('#+a\nb#-x')
    col = DiagnosticCollector()
    RawTokenizer._skip_whitespace_and_comments(stream, col, file)
    assert stream.peek() == 'x'
    assert not col.has_errors


def test_skip_unterminated_multiline_comment() -> None:
    file = _file('#+abc')
    stream = CharStream('#+abc')
    col = DiagnosticCollector()
    RawTokenizer._skip_whitespace_and_comments(stream, col, file)
    assert stream.eof()
    assert any(d.code == 'tokenize.unterminated_comment' for d in col)


def test_handle_comment_single_line() -> None:
    file = _file('#abc\n')
    stream = CharStream('#abc\n')
    col = DiagnosticCollector()
    RawTokenizer._handle_comment(stream, col, file)
    assert stream.peek() == '\n'
    assert not col.has_errors


def test_handle_comment_multiline() -> None:
    file = _file('#+x\n#-y')
    stream = CharStream('#+x\n#-y')
    col = DiagnosticCollector()
    RawTokenizer._handle_comment(stream, col, file)
    assert stream.peek() == 'y'
    assert not col.has_errors


def test_handle_comment_unterminated_multiline() -> None:
    file = _file('#+x')
    stream = CharStream('#+x')
    col = DiagnosticCollector()
    RawTokenizer._handle_comment(stream, col, file)
    assert stream.eof()
    assert any(d.code == 'tokenize.unterminated_comment' for d in col)


def test_skip_multiline_comment_matching_depth() -> None:
    file = _file('x#--y')
    stream = CharStream('x#--y')
    col = DiagnosticCollector()
    RawTokenizer._skip_multiline_comment(stream, col, file, depth=2)
    assert stream.peek() == 'y'
    assert not col.has_errors


def test_skip_multiline_comment_wrong_depth_keeps_looking() -> None:
    file = _file('#-x#--y')
    stream = CharStream('#-x#--y')
    col = DiagnosticCollector()
    RawTokenizer._skip_multiline_comment(stream, col, file, depth=2)
    assert stream.peek() == 'y'
    assert not col.has_errors


def test_skip_multiline_comment_unterminated() -> None:
    file = _file('x#-')
    stream = CharStream('x#-')
    col = DiagnosticCollector()
    RawTokenizer._skip_multiline_comment(stream, col, file, depth=2)
    assert stream.eof()
    assert any(d.code == 'tokenize.unterminated_comment' for d in col)


# ── 单字符 / 括号栈 ─────────────────────────────────


def test_single_char_consumes_and_makes_token() -> None:
    file = _file('{x')
    stream = CharStream('{x')
    tok = RawTokenizer._single_char(RawTokenType.LBRACE, stream, file)
    assert tok.type is RawTokenType.LBRACE
    assert tok.raw == '{'
    assert tok.source.start.index == 0
    assert tok.source.end.index == 1
    assert stream.peek() == 'x'


def test_track_bracket_open_pushes() -> None:
    file = _file('')
    stack: list[tuple[str, SourceInfo]] = []
    col = DiagnosticCollector()
    tok = _tok('[', file)
    RawTokenizer._track_bracket('[', tok, stack, col)
    assert stack == [('[', tok.source.start)]
    assert not col.has_errors


def test_track_bracket_matching_close_pops() -> None:
    file = _file('')
    stack: list[tuple[str, SourceInfo]] = [('[', SourceInfo(line=1, col=1, index=0))]
    col = DiagnosticCollector()
    RawTokenizer._track_bracket(']', _tok(']', file), stack, col)
    assert stack == []
    assert not col.has_errors


def test_track_bracket_mismatch_reports_and_pops() -> None:
    file = _file('')
    stack: list[tuple[str, SourceInfo]] = [('(', SourceInfo(line=1, col=1, index=0))]
    col = DiagnosticCollector()
    RawTokenizer._track_bracket(']', _tok(']', file), stack, col)
    assert stack == []
    assert any(d.code == 'tokenize.mismatched_bracket' for d in col)


def test_track_bracket_empty_close_reports() -> None:
    file = _file('')
    stack: list[tuple[str, SourceInfo]] = []
    col = DiagnosticCollector()
    RawTokenizer._track_bracket(')', _tok(')', file), stack, col)
    assert stack == []
    assert any(d.code == 'tokenize.unexpected_close_bracket' for d in col)


def test_report_unclosed_brackets_reports_in_order_and_clears() -> None:
    file = _file('')
    stack: list[tuple[str, SourceInfo]] = [
        ('[', SourceInfo(line=1, col=3, index=2)),
        ('{', SourceInfo(line=1, col=5, index=4)),
    ]
    col = DiagnosticCollector()
    RawTokenizer._report_unclosed_brackets(stack, col, file)
    assert [d.code for d in col] == ['tokenize.unterminated_bracket', 'tokenize.unterminated_bracket']
    assert stack == []


# ── ! 导入关键字 ─────────────────────────────────────


def test_read_bang_env() -> None:
    file = _file('!env ')
    stream = CharStream('!env ')
    tok = RawTokenizer._read_bang(stream, DiagnosticCollector(), file)
    assert tok is not None
    assert tok.type is RawTokenType.ENV_IMPORT
    assert tok.raw == '!env'
    assert stream.peek() == ' '


def test_read_bang_file() -> None:
    file = _file('!file ')
    stream = CharStream('!file ')
    tok = RawTokenizer._read_bang(stream, DiagnosticCollector(), file)
    assert tok is not None
    assert tok.type is RawTokenType.FILE_IMPORT
    assert tok.raw == '!file'
    assert stream.peek() == ' '


def test_read_bang_from() -> None:
    file = _file('!from ')
    stream = CharStream('!from ')
    tok = RawTokenizer._read_bang(stream, DiagnosticCollector(), file)
    assert tok is not None
    assert tok.type is RawTokenType.FROM_IMPORT
    assert tok.raw == '!from'
    assert stream.peek() == ' '


def test_read_bang_invalid_identifier() -> None:
    file = _file('!bad')
    stream = CharStream('!bad')
    col = DiagnosticCollector()
    assert RawTokenizer._read_bang(stream, col, file) is None
    assert any(d.code == 'tokenize.invalid_bang' for d in col)


def test_read_bang_typo_corrected_to_env() -> None:
    file = _file('!envv ')
    stream = CharStream('!envv ')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_bang(stream, col, file)
    assert tok is not None
    assert tok.type is RawTokenType.ENV_IMPORT
    assert tok.raw == '!env'  # envv → env（删除 v）
    assert stream.peek() == ' '
    assert any(d.code == 'tokenize.bang_corrected' for d in col)


def test_read_bang_typo_corrected_to_file() -> None:
    file = _file('!fil ')
    stream = CharStream('!fil ')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_bang(stream, col, file)
    assert tok is not None
    assert tok.type is RawTokenType.FILE_IMPORT
    assert tok.raw == '!file'  # fil → file（插入 e）
    assert any(d.code == 'tokenize.bang_corrected' for d in col)


def test_read_bang_typo_corrected_to_from() -> None:
    file = _file('!frm ')
    stream = CharStream('!frm ')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_bang(stream, col, file)
    assert tok is not None
    assert tok.type is RawTokenType.FROM_IMPORT
    assert tok.raw == '!from'  # frm → from（替换）
    assert any(d.code == 'tokenize.bang_corrected' for d in col)


def test_read_bang_far_typo_still_invalid() -> None:
    file = _file('!xyz ')
    stream = CharStream('!xyz ')
    col = DiagnosticCollector()
    assert RawTokenizer._read_bang(stream, col, file) is None
    assert any(d.code == 'tokenize.invalid_bang' for d in col)
    assert not any(d.code == 'tokenize.bang_corrected' for d in col)


def test_edit_distance() -> None:
    assert RawTokenizer._edit_distance('env', 'env') == 0
    assert RawTokenizer._edit_distance('env', 'enx') == 1
    assert RawTokenizer._edit_distance('env', '') == 3
    assert RawTokenizer._edit_distance('file', 'fil') == 1
    assert RawTokenizer._edit_distance('from', 'frm') == 1
    assert RawTokenizer._edit_distance('from', 'env') == 4


def test_nearest_bang_keyword() -> None:
    assert RawTokenizer._nearest_bang_keyword('enx') == 'env'
    assert RawTokenizer._nearest_bang_keyword('fil') == 'file'
    assert RawTokenizer._nearest_bang_keyword('frm') == 'from'
    assert RawTokenizer._nearest_bang_keyword('env') == 'env'
    assert RawTokenizer._nearest_bang_keyword('xyz') is None


def test_read_bang_eof() -> None:
    file = _file('!')
    stream = CharStream('!')
    col = DiagnosticCollector()
    assert RawTokenizer._read_bang(stream, col, file) is None
    assert any(d.code == 'tokenize.invalid_bang' for d in col)


def test_read_bang_invalid_char_consumed() -> None:
    # !@：非法字符被一次性消费，只报一次 invalid_bang（不再叠加 unknown_char）
    file = _file('!@')
    stream = CharStream('!@')
    col = DiagnosticCollector()
    assert RawTokenizer._read_bang(stream, col, file) is None
    assert [d.code for d in col] == ['tokenize.invalid_bang']
    assert stream.eof()


def test_read_bang_digit_consumed_not_relexed() -> None:
    # !5：5 被消费，不再重新解析成 INTEGER
    file = _file('!5x')
    stream = CharStream('!5x')
    col = DiagnosticCollector()
    assert RawTokenizer._read_bang(stream, col, file) is None
    assert [d.code for d in col] == ['tokenize.invalid_bang']
    assert stream.peek() == 'x'


# ── 单行字符串 ───────────────────────────────────────


def test_read_string_plain() -> None:
    file = _file('"abc"x')
    stream = CharStream('"abc"x')
    tok = RawTokenizer._read_string(stream, DiagnosticCollector(), file)
    assert tok.type is RawTokenType.STRING
    assert tok.raw == '"abc"'
    assert stream.peek() == 'x'


def test_read_string_escape() -> None:
    file = _file(r'"a\"b"x')
    stream = CharStream(r'"a\"b"x')
    tok = RawTokenizer._read_string(stream, DiagnosticCollector(), file)
    assert tok.type is RawTokenType.STRING
    assert tok.raw == r'"a\"b"'
    assert stream.peek() == 'x'


def test_read_string_unterminated_eof() -> None:
    file = _file('"abc')
    stream = CharStream('"abc')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_string(stream, col, file)
    assert tok.type is RawTokenType.STRING
    assert tok.raw == '"abc"'  # 错误恢复补全结束引号，raw 结构合法
    assert json.loads(tok.raw) == 'abc'  # 是合法 JSON 字符串
    assert any(d.code == 'tokenize.unterminated_string' for d in col)


def test_read_string_unterminated_newline() -> None:
    file = _file('"abc\n')
    stream = CharStream('"abc\n')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_string(stream, col, file)
    assert tok.type is RawTokenType.STRING
    assert tok.raw == '"abc"'  # 与 EOF 分支一致：补全结束引号，避免下游截断
    assert json.loads(tok.raw) == 'abc'
    assert stream.peek() == '\n'  # 换行未被吞掉，留给 NEWLINE token
    assert any(d.code == 'tokenize.unterminated_string' for d in col)


def test_read_string_unterminated_after_escape() -> None:
    file = _file('"ab\\')
    stream = CharStream('"ab\\')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_string(stream, col, file)
    assert tok.type is RawTokenType.STRING
    # 丢弃未完成的转义反斜杠再补引号：raw 是合法 JSON 字符串（不再产生 "ab\" 这种未闭合）
    assert tok.raw == '"ab"'
    assert json.loads(tok.raw) == 'ab'
    assert any(d.code == 'tokenize.unterminated_string' for d in col)


def test_read_string_backslash_newline_unterminated() -> None:
    # 单行字符串不允许真实换行（规范：json 风格转义）：反斜杠后遇换行 → unterminated_string
    file = _file('"abc\\\n')
    stream = CharStream('"abc\\\n')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_string(stream, col, file)
    assert tok.type is RawTokenType.STRING
    assert tok.raw == '"abc"'  # 丢弃未完成的转义反斜杠后补引号，raw 合法
    assert json.loads(tok.raw) == 'abc'
    assert any(d.code == 'tokenize.unterminated_string' for d in col)
    assert stream.peek() == '\n'  # 换行未被吞掉，留给 NEWLINE token


# ── 多行字符串 ───────────────────────────────────────


def test_read_multiline_string() -> None:
    file = _file('`abc`x')
    stream = CharStream('`abc`x')
    tok = RawTokenizer._read_multiline_string(stream, DiagnosticCollector(), file)
    assert tok.type is RawTokenType.MULTILINE_STRING
    assert tok.raw == '`abc`'
    assert stream.peek() == 'x'


def test_read_multiline_string_variable_backticks() -> None:
    file = _file('``a`b``x')
    stream = CharStream('``a`b``x')
    tok = RawTokenizer._read_multiline_string(stream, DiagnosticCollector(), file)
    assert tok.type is RawTokenType.MULTILINE_STRING
    assert tok.raw == '``a`b``'
    assert stream.peek() == 'x'


def test_read_multiline_string_unterminated() -> None:
    file = _file('`abc')
    stream = CharStream('`abc')
    col = DiagnosticCollector()
    RawTokenizer._read_multiline_string(stream, col, file)
    diags = [d for d in col if d.code == 'tokenize.unterminated_multiline_string']
    assert diags
    assert diags[0].params == {'flag': '`'}  # 期望单个反引号结束标记


def test_read_multiline_string_unterminated_reports_expected_flag() -> None:
    # 起始双反引号 → 期望 `` 结束标记（与注释 {flag} 一致）
    file = _file('``abc')
    stream = CharStream('``abc')
    col = DiagnosticCollector()
    RawTokenizer._read_multiline_string(stream, col, file)
    diags = [d for d in col if d.code == 'tokenize.unterminated_multiline_string']
    assert diags
    assert diags[0].params == {'flag': '``'}


# ── 数字 / 特殊浮点 ─────────────────────────────────


def test_read_number_integer() -> None:
    file = _file('42x')
    stream = CharStream('42x')
    tok = RawTokenizer._read_number_fallback(stream, DiagnosticCollector(), file)
    assert tok is not None
    assert tok.type is RawTokenType.INTEGER
    assert tok.raw == '42'
    assert stream.peek() == 'x'


def test_read_number_negative_integer() -> None:
    file = _file('-80x')
    stream = CharStream('-80x')
    tok = RawTokenizer._read_number_fallback(stream, DiagnosticCollector(), file)
    assert tok is not None
    assert tok.type is RawTokenType.INTEGER
    assert tok.raw == '-80'
    assert stream.peek() == 'x'


def test_read_number_float() -> None:
    file = _file('3.14x')
    stream = CharStream('3.14x')
    tok = RawTokenizer._read_number_fallback(stream, DiagnosticCollector(), file)
    assert tok is not None
    assert tok.type is RawTokenType.FLOAT
    assert tok.raw == '3.14'
    assert stream.peek() == 'x'


def test_read_number_exponent() -> None:
    file = _file('1e10x')
    stream = CharStream('1e10x')
    tok = RawTokenizer._read_number_fallback(stream, DiagnosticCollector(), file)
    assert tok is not None
    assert tok.type is RawTokenType.FLOAT
    assert tok.raw == '1e10'
    assert stream.peek() == 'x'


def test_read_number_positive_inf() -> None:
    file = _file('+inf ')
    stream = CharStream('+inf ')
    tok = RawTokenizer._read_number_fallback(stream, DiagnosticCollector(), file)
    assert tok is not None
    assert tok.type is RawTokenType.FLOAT
    assert tok.raw == '+inf'
    assert stream.peek() == ' '


def test_read_number_negative_inf() -> None:
    file = _file('-inf ')
    stream = CharStream('-inf ')
    tok = RawTokenizer._read_number_fallback(stream, DiagnosticCollector(), file)
    assert tok is not None
    assert tok.type is RawTokenType.FLOAT
    assert tok.raw == '-inf'
    assert stream.peek() == ' '


def test_read_number_invalid_sign_only() -> None:
    file = _file('+x')
    stream = CharStream('+x')
    col = DiagnosticCollector()
    assert RawTokenizer._read_number_fallback(stream, col, file) is None
    assert any(d.code == 'tokenize.invalid_number' for d in col)
    assert stream.eof()  # 整个非法序列已被跳过，不产出非法 token


def test_read_number_lone_minus_skipped() -> None:
    file = _file('- ')
    stream = CharStream('- ')
    col = DiagnosticCollector()
    assert RawTokenizer._read_number_fallback(stream, col, file) is None
    assert any(d.code == 'tokenize.invalid_number' for d in col)
    assert stream.peek() == ' '


def test_read_number_bad_exponent_completes_to_float() -> None:
    file = _file('5e ')
    stream = CharStream('5e ')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_number_fallback(stream, col, file)
    assert tok is not None
    assert tok.type is RawTokenType.FLOAT
    assert tok.raw == '5e0'  # 残缺指数补 0 恢复为合法浮点
    assert stream.peek() == ' '
    assert any(d.code == 'tokenize.invalid_number' for d in col)


def test_read_number_bad_exponent_sign_completes_to_float() -> None:
    file = _file('5e+ ')
    stream = CharStream('5e+ ')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_number_fallback(stream, col, file)
    assert tok is not None
    assert tok.type is RawTokenType.FLOAT
    assert tok.raw == '5e+0'
    assert stream.peek() == ' '
    assert any(d.code == 'tokenize.invalid_number' for d in col)


def test_read_number_bad_exponent_keeps_rest_of_input() -> None:
    # 5e+foo：残缺指数补 0 成 5e+0，foo 留在流中继续 tokenize
    file = _file('5e+foo')
    stream = CharStream('5e+foo')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_number_fallback(stream, col, file)
    assert tok is not None
    assert tok.type is RawTokenType.FLOAT
    assert tok.raw == '5e+0'
    assert stream.peek() == 'f'
    assert any(d.code == 'tokenize.invalid_number' for d in col)


def test_read_number_trailing_dot_completes_to_float() -> None:
    file = _file('42. ')
    stream = CharStream('42. ')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_number_fallback(stream, col, file)
    assert tok is not None
    assert tok.type is RawTokenType.FLOAT
    assert tok.raw == '42.0'  # 小数部分补 0 恢复为合法浮点
    assert stream.peek() == ' '
    assert any(d.code == 'tokenize.invalid_number' for d in col)  # 与 42.a 一致：残缺即报错


def test_read_number_dot_no_digits_completes_to_float() -> None:
    # 42.a：. 后无数字 → 报错并补 0 成 42.0，a 留在流中
    file = _file('42.a')
    stream = CharStream('42.a')
    col = DiagnosticCollector()
    tok = RawTokenizer._read_number_fallback(stream, col, file)
    assert tok is not None
    assert tok.type is RawTokenType.FLOAT
    assert tok.raw == '42.0'
    assert stream.peek() == 'a'
    assert any(d.code == 'tokenize.invalid_number' for d in col)


def test_read_number_invalid_alpha_skipped() -> None:
    file = _file('+foo ')
    stream = CharStream('+foo ')
    col = DiagnosticCollector()
    assert RawTokenizer._read_number_fallback(stream, col, file) is None
    assert any(d.code == 'tokenize.invalid_number' for d in col)
    assert stream.peek() == ' '


# ── 标识符 / 关键字 ─────────────────────────────────


def test_read_identifier() -> None:
    file = _file('abc_1 ')
    stream = CharStream('abc_1 ')
    tok = RawTokenizer._read_identifier_or_keyword(stream, file)
    assert tok.type is RawTokenType.IDENTIFIER
    assert tok.raw == 'abc_1'
    assert stream.peek() == ' '


def test_read_keyword() -> None:
    file = _file('null ')
    stream = CharStream('null ')
    tok = RawTokenizer._read_identifier_or_keyword(stream, file)
    assert tok.type is RawTokenType.NULL
    assert tok.raw == 'null'
