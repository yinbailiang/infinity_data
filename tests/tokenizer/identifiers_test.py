"""tokenizer/identifiers.py 单元测试：裸标识符判定与 canonical 渲染。"""

from infinity_data.tokenizer.identifiers import (
    RESERVED_LITERAL_NAMES,
    is_bare_identifier,
    quote_identifier,
    render_identifier,
)


def test_reserved_literals() -> None:
    assert RESERVED_LITERAL_NAMES == frozenset({'null', 'noexist', 'true', 'false', 'nan'})


def test_is_bare_identifier_accepts_ident_charset() -> None:
    assert is_bare_identifier('abc')
    assert is_bare_identifier('_a1')
    assert is_bare_identifier('A_z9')


def test_is_bare_identifier_rejects_special_or_reserved() -> None:
    assert not is_bare_identifier('')
    assert not is_bare_identifier('1a')
    assert not is_bare_identifier('a-b')
    assert not is_bare_identifier('a.b')
    assert not is_bare_identifier('a b')
    assert not is_bare_identifier('名字')
    assert not is_bare_identifier('true')
    assert not is_bare_identifier('noexist')


def test_render_identifier_normalizes() -> None:
    assert render_identifier('abc') == 'abc'
    assert render_identifier('a-b') == "'a-b'"
    assert render_identifier('true') == "'true'"


def test_quote_identifier_escapes() -> None:
    assert quote_identifier('a-b') == "'a-b'"
    assert quote_identifier("a'b") == "'a\\'b'"
    assert quote_identifier('a\\b') == "'a\\\\b'"


def test_quote_identifier_uses_json_escapes() -> None:
    """canonical 复用 JSON 转义：控制字符 → \\n / \\uXXXX，双引号无需转义。"""
    assert quote_identifier('a\nb') == "'a\\nb'"
    assert quote_identifier('a"b') == "'a\"b'"
    assert quote_identifier('a\x01b') == "'a\\u0001b'"
    assert quote_identifier('名字') == "'名字'"
