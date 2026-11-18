"""parser/diagnostics.py 单元测试：parse.* 声明注册与渲染（导入即注册）。"""

from infinity_data.infra.diagnostics import Diagnostic
from infinity_data.parser.diagnostics import (
    ParseAssertMissingConstraint,
    ParseInvalidCast,
    ParseMissingSeparator,
    ParseStringIdentifierMisplaced,
    ParseUnexpectedToken,
    ParseUnrecognizedStatement,
)


def test_separator_vocab_registered() -> None:
    msg = Diagnostic(ParseMissingSeparator(), lang='zh-CN').render(include_location=False)
    assert '缺少分隔符' in msg


def test_unexpected_token_vocab() -> None:
    msg = Diagnostic(ParseUnexpectedToken(expected='A', actual='B'), lang='zh-CN').render(include_location=False)
    assert 'A' in msg and 'B' in msg


def test_unrecognized_statement_vocab() -> None:
    msg = Diagnostic(ParseUnrecognizedStatement(name='X'), lang='zh-CN').render(include_location=False)
    assert '无法识别' in msg


def test_invalid_cast_vocab() -> None:
    msg = Diagnostic(ParseInvalidCast(type='foo'), lang='zh-CN').render(include_location=False)
    assert '类型转换' in msg


def test_assert_missing_constraint_vocab() -> None:
    msg = Diagnostic(ParseAssertMissingConstraint(), lang='zh-CN').render(include_location=False)
    assert '!assert' in msg and '约束' in msg


def test_string_identifier_misplaced_vocab() -> None:
    msg = Diagnostic(ParseStringIdentifierMisplaced(name='a-b'), lang='zh-CN').render(include_location=False)
    assert '字段名' in msg and 'a-b' in msg
