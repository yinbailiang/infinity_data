"""tokenizer/models/tokens.py 单元测试：Token 类型与抽象字符串基类。"""

import pytest

from infinity_data.infra.location import SourceRange
from infinity_data.tokenizer.models.raw_tokens import RawToken, RawTokenType
from infinity_data.tokenizer.models.tokens import (
    BareIdentifierToken,
    IdentifierToken,
    IntegerToken,
    SinglelineStringToken,
    StringIdentifierToken,
    StringToken,
)


def _raw(tt: RawTokenType, raw: str) -> RawToken:
    return RawToken(type=tt, raw=raw, source=SourceRange.empty())


def test_string_token_base_not_instantiable() -> None:
    with pytest.raises(TypeError):
        StringToken()


def test_singleline_string_is_string_token() -> None:
    t = SinglelineStringToken(raw=_raw(RawTokenType.STRING, '"hi"'), value='hi')
    assert isinstance(t, StringToken)
    assert t.value == 'hi'


def test_identifier_base_is_abstract() -> None:
    assert IdentifierToken.__abstractmethods__ == frozenset({'canonical'})


def test_bare_identifier_name() -> None:
    t = BareIdentifierToken(raw=_raw(RawTokenType.IDENTIFIER, 'abc'), name='abc')
    assert t.name == 'abc'
    assert isinstance(t, IdentifierToken)
    assert t.canonical() == 'abc'


def test_string_identifier_canonical_quotes_and_escapes() -> None:
    t = StringIdentifierToken(raw=_raw(RawTokenType.STRING_IDENTIFIER, "'a-b'"), name='a-b')
    assert isinstance(t, IdentifierToken)
    assert t.canonical() == "'a-b'"

    escaped = StringIdentifierToken(raw=_raw(RawTokenType.STRING_IDENTIFIER, "'a'b'"), name="a'b")
    assert escaped.canonical() == "'a\\'b'"


def test_literal_value() -> None:
    t = IntegerToken(raw=_raw(RawTokenType.INTEGER, '42'), value=42)
    assert t.value == 42


def test_token_carries_raw_source() -> None:
    t = BareIdentifierToken(raw=_raw(RawTokenType.IDENTIFIER, 'x'), name='x')
    assert t.raw.source == SourceRange.empty()
