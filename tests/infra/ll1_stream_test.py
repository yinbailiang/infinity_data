"""infra/ll1_stream.py 单元测试：LL(1) 预读流的 peek/advance/eof 语义。"""

import pytest

from infinity_data.infra.ll1_stream import LL1Stream, NoNextType


def test_peek_is_lazy_and_repeatable() -> None:
    stream = LL1Stream[int](iter([1, 2, 3]))
    assert stream.peek() == 1
    assert stream.peek() == 1  # 预读不消费


def test_advance_consumes() -> None:
    stream = LL1Stream[int](iter([1, 2, 3]))
    assert stream.advance() == 1
    assert stream.peek() == 2
    assert not stream.eof()


def test_consume_all() -> None:
    stream = LL1Stream[int](iter([1, 2, 3]))
    got: list[int] = []
    while not stream.eof():
        got.append(stream.advance())
    assert got == [1, 2, 3]


def test_eof_at_end() -> None:
    stream = LL1Stream[int](iter([1]))
    assert not stream.eof()
    stream.advance()
    assert stream.eof()
    assert isinstance(stream.peek(), NoNextType)


def test_empty_stream_eof() -> None:
    stream = LL1Stream[int](iter([]))
    assert stream.eof()
    assert isinstance(stream.peek(), NoNextType)


def test_advance_at_end_raises() -> None:
    stream = LL1Stream[int](iter([1]))
    stream.advance()
    with pytest.raises(IndexError):
        stream.advance()
