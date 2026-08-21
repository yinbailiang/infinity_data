"""tokenizer/char_stream.py 单元测试：CharStream 行列位置跟踪。"""

from infinity_data.tokenizer.char_stream import CharStream


def test_line_col_tracking() -> None:
    stream = CharStream(iter('ab\ncd'))
    assert (stream.line, stream.col) == (1, 1)
    stream.advance()  # a
    stream.advance()  # b
    assert (stream.line, stream.col) == (1, 3)
    stream.advance()  # \n
    assert (stream.line, stream.col) == (2, 1)
    stream.advance()  # c
    assert (stream.line, stream.col) == (2, 2)


def test_index_tracking() -> None:
    stream = CharStream(iter('abc'))
    assert stream.index == 0
    stream.advance()
    stream.advance()
    assert stream.index == 2


def test_eof() -> None:
    stream = CharStream(iter('a'))
    assert not stream.eof()
    stream.advance()
    assert stream.eof()


def test_info() -> None:
    stream = CharStream(iter('x\ny'))
    info = stream.info()
    assert (info.line, info.col, info.index) == (1, 1, 0)


def test_crlf_treated_as_single_newline() -> None:
    # CRLF：\n 触发换行，后续位置正确（\r 虚占列被 \n 重置）
    stream = CharStream(iter('a\r\nb'))
    stream.advance()  # a
    stream.advance()  # \r
    stream.advance()  # \n
    assert (stream.line, stream.col) == (2, 1)
    stream.advance()  # b
    assert (stream.line, stream.col) == (2, 2)


def test_lone_cr_not_a_newline() -> None:
    # 单 \r（老 Mac CR）不支持换行，视为普通字符
    stream = CharStream(iter('a\rb'))
    stream.advance()  # a
    stream.advance()  # \r
    assert (stream.line, stream.col) == (1, 3)
    stream.advance()  # b
    assert (stream.line, stream.col) == (1, 4)
