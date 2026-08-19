"""tokenizer/finalizer.py 单元测试：FinalTokenizer 值转换。"""

from pathlib import Path

from infinity_data.infra.file import MemFile
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.models.tokens import EofToken, IdentifierToken, IntegerToken, StringToken
from infinity_data.tokenizer.tokenizer import RawTokenizer


def _final(src: str):
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    return list(FinalTokenizer(RawTokenizer(file=file)))


def test_identifier_and_integer_values() -> None:
    toks = _final('a = 42\n')
    assert isinstance(toks[0], IdentifierToken)
    assert toks[0].name == 'a'
    assert isinstance(toks[2], IntegerToken)
    assert toks[2].value == 42


def test_string_value() -> None:
    toks = _final('x = "hi"\n')
    assert isinstance(toks[2], StringToken)
    assert toks[2].value == 'hi'


def test_eof_token_present() -> None:
    toks = _final('')
    assert isinstance(toks[-1], EofToken)


def test_escapes_resolved() -> None:
    toks = _final('x = "a\\n\\t\\""\n')
    assert isinstance(toks[2], StringToken)
    assert toks[2].value == 'a\n\t"'
