"""tokenizer/diagnostics.py 单元测试：tokenize.* 声明注册与渲染（导入即注册）。"""

from infinity_data.infra.diagnostics import Diagnostic, DiagnosticDeclaration
from infinity_data.tokenizer.diagnostics import (
    TokenizeBangCorrected,
    TokenizeBom,
    TokenizeEmptyIdentifier,
    TokenizeMismatchedBracket,
    TokenizeRedundantIdentifierQuotes,
    TokenizeSignedNan,
    TokenizeUnexpectedCloseBracket,
    TokenizeUnknownChar,
    TokenizeUnterminatedBracket,
    TokenizeUnterminatedIdentifier,
    TokenizeUnterminatedMultilineString,
    TokenizeUnterminatedString,
)


def _msg(declaration: DiagnosticDeclaration) -> str:
    return Diagnostic(declaration, lang='zh-CN').render(include_location=False)


def test_vocab_registered() -> None:
    assert '未知字符' in _msg(TokenizeUnknownChar(char='@'))
    assert '括号未闭合' in _msg(TokenizeUnterminatedBracket(bracket='['))
    assert '不匹配' in _msg(TokenizeMismatchedBracket(open='[', close=')'))
    assert '多余' in _msg(TokenizeUnexpectedCloseBracket(bracket=')'))
    assert '纠正' in _msg(TokenizeBangCorrected(actual='envv', suggestion='env'))
    assert '带符号' in _msg(TokenizeSignedNan(raw='+nan'))
    assert 'BOM' in _msg(TokenizeBom())
    assert '未闭合' in _msg(TokenizeUnterminatedString())
    assert '多行字符串未闭合' in _msg(TokenizeUnterminatedMultilineString(flag='``'))
    assert '未闭合' in _msg(TokenizeUnterminatedIdentifier())
    assert '不能为空' in _msg(TokenizeEmptyIdentifier())
    assert '裸写' in _msg(TokenizeRedundantIdentifierQuotes(name='abc'))
