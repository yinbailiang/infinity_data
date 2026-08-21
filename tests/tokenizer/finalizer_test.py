"""tokenizer/finalizer.py 单元测试：FinalTokenizer 值转换（收集 + 恢复）。"""

from pathlib import Path

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.models.tokens import (
    EofToken,
    FloatToken,
    IdentifierToken,
    IntegerToken,
    StringToken,
    Token,
)
from infinity_data.tokenizer.tokenizer import RawTokenizer


def _final(src: str) -> tuple[list[Token], DiagnosticCollector]:
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    collector = DiagnosticCollector()
    tokens = list(FinalTokenizer(RawTokenizer(file=file, error_collector=collector), error_collector=collector))
    return tokens, collector


def test_identifier_and_integer_values() -> None:
    toks, _ = _final('a = 42\n')
    assert isinstance(toks[0], IdentifierToken)
    assert toks[0].name == 'a'
    assert isinstance(toks[2], IntegerToken)
    assert toks[2].value == 42


def test_string_value() -> None:
    toks, _ = _final('x = "hi"\n')
    assert isinstance(toks[2], StringToken)
    assert toks[2].value == 'hi'


def test_eof_token_present() -> None:
    toks, _ = _final('')
    assert isinstance(toks[-1], EofToken)


def test_escapes_resolved() -> None:
    toks, _ = _final('x = "a\\n\\t\\""\n')
    assert isinstance(toks[2], StringToken)
    assert toks[2].value == 'a\n\t"'


# ── 容错收集：转换失败不抛异常，收集诊断并产出恢复 token ──


def test_invalid_escape_collected_and_recovered() -> None:
    """无效转义（\\q）→ 收集 tokenize.invalid_escape，恢复为去引号原文。"""
    toks, col = _final('x = "a\\qb"\n')
    assert any(d.code == 'tokenize.invalid_escape' for d in col)
    assert isinstance(toks[2], StringToken)
    assert toks[2].value == 'a\\qb'


def test_invalid_unicode_escape_collected() -> None:
    _, col = _final('x = "\\u"\n')
    assert any(d.code == 'tokenize.invalid_escape' for d in col)


def test_malformed_exponent_handled_at_lexer() -> None:
    """残缺指数（1e）→ 词法层即报 tokenize.invalid_number，补 0 恢复为合法浮点 1e0。"""
    toks, col = _final('x = 1e\n')
    assert any(d.code == 'tokenize.invalid_number' for d in col)
    assert isinstance(toks[2], FloatToken)
    assert toks[2].value == 1  # Decimal('1e0')
