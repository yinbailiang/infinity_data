"""tokenizer/models/tokens.py 单元测试：Token 类型与抽象字符串基类。"""

import pytest

from infinity_data.infra.location import SourceRange
from infinity_data.tokenizer.models.raw_tokens import RawToken, RawTokenType
from infinity_data.tokenizer.models.tokens import (
    IdentifierToken,
    IntegerToken,
    SinglelineStringToken,
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


def test_identifier_name() -> None:
    t = IdentifierToken(raw=_raw(RawTokenType.IDENTIFIER, 'abc'), name='abc')
    assert t.name == 'abc'


def test_literal_value() -> None:
    t = IntegerToken(raw=_raw(RawTokenType.INTEGER, '42'), value=42)
    assert t.value == 42


def test_token_carries_raw_source() -> None:
    t = IdentifierToken(raw=_raw(RawTokenType.IDENTIFIER, 'x'), name='x')
    assert t.raw.source == SourceRange.empty()
