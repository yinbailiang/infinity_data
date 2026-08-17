"""词法分析器"""

from infinity_data.infra.file import File
from infinity_data.infra.ll1_stream import NoNextType
from infinity_data.tokenizer.char_stream import CharStream
from infinity_data.tokenizer.errors import (
    InvalidBangError,
    InvalidNumberError,
    TokenizeErrorCollector,
    UnknownCharError,
    UnterminatedCommentError,
    UnterminatedStringError,
)
from infinity_data.tokenizer.models.raw_tokens import (
    RawToken,
    RawTokenType,
    SourceInfo,
    SourceRange,
)


class RawTokenizer:
    """将 infd/inft 源码转为 RawToken 流。"""

    _single_char_map: dict[str, RawTokenType] = {
        '{': RawTokenType.LBRACE,
        '}': RawTokenType.RBRACE,
        '[': RawTokenType.LBRACKET,
        ']': RawTokenType.RBRACKET,
        '(': RawTokenType.LPAREN,
        ')': RawTokenType.RPAREN,
        '<': RawTokenType.LANGLE,
        '>': RawTokenType.RANGLE,
        '=': RawTokenType.EQUALS,
        ':': RawTokenType.COLON,
        ',': RawTokenType.COMMA,
        '~': RawTokenType.TILDE,
        '?': RawTokenType.QUESTION,
        '$': RawTokenType.DOLLAR,
        '.': RawTokenType.DOT,
        '\n': RawTokenType.NEWLINE,
    }

    _keywords_map: dict[str, RawTokenType] = {
        'null': RawTokenType.NULL,
        'noexist': RawTokenType.NOEXIST,
        'true': RawTokenType.BOOL,
        'false': RawTokenType.BOOL,
        'nan': RawTokenType.FLOAT,
    }

    def __init__(
        self,
        file: File,
        error_collector: TokenizeErrorCollector | None = None,
    ) -> None:
        self._file: File = file
        self._stream: CharStream = CharStream(file.chars())
        # 注意：不能用 `or` —— 空 ErrorCollector 的 __bool__ 为 False，会静默丢弃传入的收集器
        self._errors = error_collector if error_collector is not None else TokenizeErrorCollector()
        self._eof_sent: bool = False

    def __iter__(self) -> 'RawTokenizer':
        return self

    def __next__(self) -> RawToken:
        if self._eof_sent:
            raise StopIteration
        tok: RawToken = self.next()
        if tok.type is RawTokenType.EOF:
            self._eof_sent = True
        return tok

    @property
    def error_collector(self) -> TokenizeErrorCollector:
        return self._errors

    @property
    def file(self) -> File:
        return self._file

    def _current_source_info(self) -> SourceInfo:
        return self._stream.info()

    def next(self) -> RawToken:
        """返回下一个 token。"""
        while True:
            self._skip_whitespace_and_comments()

            if self._stream.eof():
                return self._make_token(RawTokenType.EOF, '', self._current_source_info())

            ch = self._stream.peek()
            assert not isinstance(ch, NoNextType)

            if ch in self._single_char_map:
                return self._single_char(self._single_char_map[ch])

            if ch == '!':
                tok = self._read_bang()
                if tok is not None:
                    return tok
                continue  # 词法错误已报，跳过该 ! 序列

            if ch == '"':
                return self._read_string()

            if ch == '`':
                return self._read_multiline_string()

            if ch.isdigit() or ch in ['+', '-']:
                return self._read_number_fallback()

            # ── 标识符 / 关键字 ───────────────────────
            if ch.isalpha() or ch == '_':
                return self._read_identifier_or_keyword()

            # ── 无法识别的字符 ────────────────────────
            self._errors.add(
                UnknownCharError(
                    char=ch,
                    source=SourceRange.at(self._file, self._current_source_info()),
                )
            )
            self._stream.advance()

    def _make_token(
        self,
        token_type: RawTokenType,
        raw: str,
        start: SourceInfo,
    ) -> RawToken:
        return RawToken(
            type=token_type,
            raw=raw,
            source=SourceRange(
                file=self._file,
                start=start,
                end=self._current_source_info(),
            ),
        )

    # ── 空白与注释跳过 ────────────────────────────────

    def _skip_whitespace_and_comments(self) -> None:
        """跳过空白及注释（单行 # 和多行 #+...#-）。"""
        while not self._stream.eof():
            ch = self._stream.peek()
            assert not isinstance(ch, NoNextType)

            # 跳过除换行外的空白
            if ch != '\n' and ch.isspace():
                self._stream.advance()
                continue

            # 单行注释: # 到行尾
            if ch == '#':
                self._handle_comment()
                continue

            break

    def _handle_comment(self) -> None:
        """处理注释：单行 # 或多行 #+...#-"""
        self._stream.advance()  # 消费 '#'

        if self._stream.eof():
            return

        ch = self._stream.peek()
        assert not isinstance(ch, NoNextType)

        # 检查是否为多行注释起始标记 #+
        plus_count = 0
        while ch == '+':
            plus_count += 1
            self._stream.advance()
            if self._stream.eof():
                self._errors.add(
                    UnterminatedCommentError(
                        SourceRange.at(self._file, self._current_source_info()),
                        flag='#' + '-' * plus_count,
                    )
                )
                return
            ch = self._stream.peek()
            assert not isinstance(ch, NoNextType)

        if plus_count > 0:
            # 多行注释模式: 需要找到匹配的 # + '-' * plus_count
            self._skip_multiline_comment(plus_count)
        else:
            # 单行注释: 跳到行尾
            while not self._stream.eof() and self._stream.peek() != '\n':
                self._stream.advance()

    def _skip_multiline_comment(self, depth: int) -> None:
        """跳过多行注释直到找到匹配的结束标记 # + '-' * depth。"""
        while not self._stream.eof():
            ch = self._stream.peek()
            assert not isinstance(ch, NoNextType)

            if ch == '#':
                self._stream.advance()
                if self._stream.eof():
                    break
                # 检查后续字符是否全是 '-'
                minus_count = 0
                while not self._stream.eof() and self._stream.peek() == '-':
                    minus_count += 1
                    self._stream.advance()
                if minus_count == depth:
                    return
                continue

            self._stream.advance()

        self._errors.add(
            UnterminatedCommentError(
                SourceRange.at(self._file, self._current_source_info()),
                flag='#' + '-' * depth,
            )
        )

    # ── 单字符 token ──────────────────────────────────
    def _single_char(self, token_type: RawTokenType) -> RawToken:
        ch = self._stream.peek()
        assert not isinstance(ch, NoNextType)
        start = self._current_source_info()
        self._stream.advance()
        return self._make_token(token_type, ch, start=start)

    # ── ! 导入关键字（词法组合，! 无独立语法）──

    def _read_bang(self) -> RawToken | None:
        """读取 ``!`` 起始的 token。

        - ``!env`` / ``!file`` / ``!from`` → 组合导入关键字 token
        - 其他任何情况 → 词法错误（语言不允许单独 ``!``），返回 None 跳过
        """
        start = self._current_source_info()
        self._stream.advance()  # 消费 '!'

        if self._stream.eof():
            self._errors.add(InvalidBangError(actual='EOF', source=SourceRange.at(self._file, start)))
            return None
        ch = self._stream.peek()
        assert not isinstance(ch, NoNextType)
        if not (ch.isalpha() or ch == '_'):
            self._errors.add(InvalidBangError(actual=repr(ch), source=SourceRange.at(self._file, start)))
            return None

        ident_tok = self._read_identifier_or_keyword()
        match ident_tok.raw:
            case 'env':
                return self._make_token(RawTokenType.ENV_IMPORT, '!env', start=start)
            case 'file':
                return self._make_token(RawTokenType.FILE_IMPORT, '!file', start=start)
            case 'from':
                return self._make_token(RawTokenType.FROM_IMPORT, '!from', start=start)
            case _:
                self._errors.add(InvalidBangError(actual=repr(ident_tok.raw), source=SourceRange.at(self._file, start)))
                return None

    # ── 单行字符串 ────────────────────────────────────

    def _read_string(self) -> RawToken:
        """读取双引号包裹的单行字符串"""
        start = self._current_source_info()
        raw_parts: list[str] = [self._stream.advance()]  # 消费 '"'

        while not self._stream.eof():
            ch = self._stream.peek()
            assert not isinstance(ch, NoNextType)

            if ch == '\\':
                raw_parts.append(self._stream.advance())
                if self._stream.eof():
                    self._errors.add(
                        UnterminatedStringError(
                            str_type=RawTokenType.STRING,
                            source=SourceRange.at(self._file, start),
                        )
                    )
                    return self._make_token(RawTokenType.STRING, ''.join(raw_parts), start=start)
                raw_parts.append(self._stream.advance())
                continue

            if ch == '"':
                raw_parts.append(ch)
                self._stream.advance()
                return self._make_token(RawTokenType.STRING, ''.join(raw_parts), start=start)

            if ch == '\n':
                self._errors.add(
                    UnterminatedStringError(
                        str_type=RawTokenType.STRING,
                        source=SourceRange.at(self._file, start),
                    )
                )
                return self._make_token(RawTokenType.STRING, ''.join(raw_parts), start=start)

            raw_parts.append(ch)
            self._stream.advance()

        self._errors.add(
            UnterminatedStringError(str_type=RawTokenType.STRING, source=SourceRange.at(self._file, start))
        )
        raw_parts.append('"')  # 补上缺失的结束引号
        return self._make_token(RawTokenType.STRING, ''.join(raw_parts), start=start)

    # ── 多行字符串（Markdown 风格） ────────────────────

    def _read_multiline_string(self) -> RawToken:
        """读取反引号包裹的多行字符串。

        语法: `...`
        - 起始 ` 可变长（>= 1 个反引号）
        """
        start = self._current_source_info()

        # 统计起始反引号数量
        backtick_count = 0
        while not self._stream.eof():
            ch = self._stream.peek()
            if ch == '`':
                backtick_count += 1
                self._stream.advance()
            else:
                break

        # 读取内容直到匹配的结束反引号
        raw = '`' * backtick_count
        while not self._stream.eof():
            ch = self._stream.peek()
            assert not isinstance(ch, NoNextType)

            if ch == '`':
                # 检查是否有足够的反引号匹配
                temp_count = 0
                while not self._stream.eof() and self._stream.peek() == '`':
                    temp_count += 1
                    self._stream.advance()
                if temp_count >= backtick_count:
                    raw += '`' * temp_count
                    return self._make_token(RawTokenType.MULTILINE_STRING, raw, start=start)
                else:
                    raw += '`' * temp_count
                    continue

            raw += ch
            self._stream.advance()

        self._errors.add(
            UnterminatedStringError(str_type=RawTokenType.MULTILINE_STRING, source=SourceRange.at(self._file, start))
        )
        raw += '`' * backtick_count
        return self._make_token(RawTokenType.MULTILINE_STRING, raw, start=start)

    # ── 数字 / 特殊浮点字面量 ─────────────────────────

    def _read_number_fallback(self) -> RawToken:
        """读取数字或特殊浮点字面量（nan, +inf, -inf）。

        支持的格式：
        - 整数: 42, -80
        - 浮点: 3.14, 5.0, 1e10, 2.5e-3
        - 特殊: +inf, -inf（nan 由关键字路径处理）
        """
        start = self._current_source_info()
        raw_parts: list[str] = []
        is_float = False

        # ── 1. 可选正负号 ──
        ch = self._stream.peek()
        if not isinstance(ch, NoNextType) and ch in '+-':
            raw_parts.append(ch)
            self._stream.advance()

        # ── 检查是否为特殊字面量 ──
        if raw_parts and raw_parts[0] in '+-':
            ch = self._stream.peek()
            if not isinstance(ch, NoNextType) and ch.isalpha():
                # 尝试读取标识符 (如 +inf, -inf)
                ident_parts: list[str] = []
                while not self._stream.eof():
                    c = self._stream.peek()
                    if not isinstance(c, NoNextType) and (c.isalnum() or c == '_'):
                        ident_parts.append(c)
                        self._stream.advance()
                    else:
                        break
                ident = ''.join(ident_parts)
                full = raw_parts[0] + ident
                if full == '+inf':
                    return self._make_token(RawTokenType.FLOAT, full, start=start)
                if full == '-inf':
                    return self._make_token(RawTokenType.FLOAT, full, start=start)
                self._errors.add(InvalidNumberError(raw=full, source=SourceRange.at(self._file, start)))
                return self._make_token(RawTokenType.IDENTIFIER, full, start=start)

        # ── 2. 整数部分 ──
        ch = self._stream.peek()
        if not isinstance(ch, NoNextType) and ch.isdigit():
            raw_parts.append(ch)
            self._stream.advance()
            while not self._stream.eof():
                ch = self._stream.peek()
                if not isinstance(ch, NoNextType) and ch.isdigit():
                    raw_parts.append(ch)
                    self._stream.advance()
                else:
                    break

        # ── 3. 可选小数部分 ──
        ch = self._stream.peek()
        if ch == '.':
            self._stream.advance()  # 消费 '.'
            if not self._stream.eof():
                next_ch = self._stream.peek()
                if not isinstance(next_ch, NoNextType) and next_ch.isdigit():
                    is_float = True
                    raw_parts.append('.')
                    raw_parts.append(next_ch)
                    self._stream.advance()
                    while not self._stream.eof():
                        ch = self._stream.peek()
                        if not isinstance(ch, NoNextType) and ch.isdigit():
                            raw_parts.append(ch)
                            self._stream.advance()
                        else:
                            break
                else:
                    # 有前置数字但 . 后无数字 (如 "42.") → 记录错误
                    self._errors.add(
                        InvalidNumberError(raw=''.join(raw_parts) + '.', source=SourceRange.at(self._file, start))
                    )

        # ── 4. 可选指数部分 ──
        ch = self._stream.peek()
        if not isinstance(ch, NoNextType) and ch in ['e', 'E']:
            raw_parts.append(ch)
            self._stream.advance()
            is_float = True

            if not self._stream.eof():
                ch = self._stream.peek()
                if not isinstance(ch, NoNextType) and ch in '+-':
                    raw_parts.append(ch)
                    self._stream.advance()

            if self._stream.eof():
                self._errors.add(InvalidNumberError(raw=''.join(raw_parts), source=SourceRange.at(self._file, start)))
            else:
                ch = self._stream.peek()
                if not isinstance(ch, NoNextType) and ch.isdigit():
                    raw_parts.append(ch)
                    self._stream.advance()
                    while not self._stream.eof():
                        ch = self._stream.peek()
                        if not isinstance(ch, NoNextType) and ch.isdigit():
                            raw_parts.append(ch)
                            self._stream.advance()
                        else:
                            break
                else:
                    self._errors.add(
                        InvalidNumberError(raw=''.join(raw_parts), source=SourceRange.at(self._file, start))
                    )

        # ── 5. 确保至少有一位数字 ──
        raw = ''.join(raw_parts)
        if not any(c.isdigit() for c in raw):
            self._errors.add(InvalidNumberError(raw=''.join(raw_parts), source=SourceRange.at(self._file, start)))

        token_type = RawTokenType.FLOAT if is_float else RawTokenType.INTEGER
        return self._make_token(token_type, raw, start=start)

    # ── 标识符 / 关键字 ───────────────────────────────

    def _read_identifier_or_keyword(self) -> RawToken:
        """读取标识符，识别关键字。"""
        start = self._current_source_info()
        raw_parts: list[str] = []

        while not self._stream.eof():
            ch = self._stream.peek()
            if not isinstance(ch, NoNextType) and (ch.isalnum() or ch == '_'):
                raw_parts.append(ch)
                self._stream.advance()
            else:
                break

        raw = ''.join(raw_parts)
        token_type = self._keywords_map.get(raw, RawTokenType.IDENTIFIER)
        return self._make_token(token_type, raw, start=start)
