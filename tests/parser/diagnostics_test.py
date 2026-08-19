"""parser/diagnostics.py 单元测试：parse.* 词汇表注册（导入即注册）。"""

from infinity_data.infra.diagnostics import render_message


def test_separator_vocab_registered() -> None:
    assert '缺少分隔符' in render_message('parse.missing_separator', {}, location='x:1:1')


def test_unexpected_token_vocab() -> None:
    msg = render_message('parse.unexpected_token', {'expected': 'A', 'actual': 'B'}, location='x:1:1')
    assert 'A' in msg and 'B' in msg


def test_unrecognized_statement_vocab() -> None:
    assert '无法识别' in render_message('parse.unrecognized_statement', {'name': 'X'}, location='x:1:1')


def test_invalid_cast_vocab() -> None:
    assert '类型转换' in render_message('parse.invalid_cast', {'type': 'foo'}, location='x:1:1')
