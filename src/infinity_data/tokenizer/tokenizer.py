"""词法分析器"""

from collections.abc import AsyncIterable

from infinity_data.tokenizer.errors import (
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
from infinity_data.tokenizer.stream import CharStream


class RawTokenizer:
    """将 infd/inft 源码转为 RawToken 流。"""

    _single_char_map: dict[str, RawTokenType] = {
        "{": RawTokenType.LBRACE,
        "}": RawTokenType.RBRACE,
        "[": RawTokenType.LBRACKET,
        "]": RawTokenType.RBRACKET,
        "(": RawTokenType.LPAREN,
        ")": RawTokenType.RPAREN,
        "<": RawTokenType.LANGLE,
        ">": RawTokenType.RANGLE,
        "=": RawTokenType.EQUALS,
        ":": RawTokenType.COLON,
        ",": RawTokenType.COMMA,
        "~": RawTokenType.TILDE,
        "!": RawTokenType.EXCLAMATION,
        "?": RawTokenType.QUESTION,
        "$": RawTokenType.DOLLAR,
        ".": RawTokenType.DOT,
        "\n": RawTokenType.NEWLINE,
    }

    _keywords_map: dict[str, RawTokenType] = {
        "null": RawTokenType.NULL,
        "noexist": RawTokenType.NOEXIST,
        "true": RawTokenType.BOOL,
        "false": RawTokenType.BOOL,
        "nan": RawTokenType.FLOAT,

        "import": RawTokenType.IMPORT,
        "from": RawTokenType.FROM,
        "env": RawTokenType.ENV,
        "file": RawTokenType.FILE,
        "as": RawTokenType.AS,
    }

    def __init__(
        self,
        source: AsyncIterable[str],
        file_path: str = "unknown",
        error_collector: TokenizeErrorCollector | None = None,
    ) -> None:
        self._file_path: str = file_path
        self._stream: CharStream = CharStream(source)
        self._errors: TokenizeErrorCollector = error_collector or TokenizeErrorCollector()


    def __aiter__(self) -> 'RawTokenizer':
        return self

    async def __anext__(self) -> RawToken:
        tok: RawToken = await self.next()
        if tok.type is RawTokenType.EOF:
            raise StopAsyncIteration
        return tok


    @property
    def error_collector(self) -> TokenizeErrorCollector:
        return self._errors

    @property
    def file_path(self) -> str:
        return self._file_path

    def _current_source_info(self) -> SourceInfo:
        return self._stream.info(file_path=self._file_path)
    
    async def next(self) -> RawToken:
        """异步返回下一个 token。"""
        while True:
            await self._skip_whitespace_and_comments()

            if await self._stream.eof():
                return self._make_token(RawTokenType.EOF, "", self._current_source_info())

            ch = await self._stream.current()
            assert ch is not None

            
            if ch in self._single_char_map:
                return await self._single_char(self._single_char_map[ch])

            if ch == '"':
                return await self._read_string()

            if ch == "`":
                return await self._read_multiline_string()

            if ch.isdigit() or ch in ["+", "-"]:
                return await self._read_number_fallback()

            # ── 标识符 / 关键字 ───────────────────────
            if ch.isalpha() or ch == "_":
                return await self._read_identifier_or_keyword()

            # ── 无法识别的字符 ────────────────────────
            self._errors.add(
                UnknownCharError(
                    char=ch,
                    source=self._current_source_info(),
                )
            )
            await self._stream.advance()

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
                start=start,
                end=self._current_source_info(),
            )
        )

    # ── 空白与注释跳过 ────────────────────────────────

    async def _skip_whitespace_and_comments(self) -> None:
        """跳过空白及注释（单行 # 和多行 #+...#-）。"""
        while not await self._stream.eof():
            ch = await self._stream.current()
            assert ch is not None

            # 跳过除换行外的空白
            if ch != "\n" and ch.isspace():
                await self._stream.advance()
                continue

            # 单行注释: # 到行尾
            if ch == "#":
                await self._handle_comment()
                continue

            break

    async def _handle_comment(self) -> None:
        """处理注释：单行 # 或多行 #+...#-"""
        await self._stream.advance()  # 消费 '#'

        if await self._stream.eof():
            return

        ch = await self._stream.current()
        assert ch is not None

        # 检查是否为多行注释起始标记 #+
        plus_count = 0
        while ch == "+":
            plus_count += 1
            await self._stream.advance()
            if await self._stream.eof():
                self._errors.add(
                    UnterminatedCommentError(self._current_source_info(), flag="#" + "+" * plus_count)
                )
                return
            ch = await self._stream.current()
            assert ch is not None

        if plus_count > 0:
            # 多行注释模式: 需要找到匹配的 # + '-' * plus_count
            await self._skip_multiline_comment(plus_count)
        else:
            # 单行注释: 跳到行尾
            while not await self._stream.eof() and await self._stream.current() != "\n":
                await self._stream.advance()

    async def _skip_multiline_comment(self, depth: int) -> None:
        """跳过多行注释直到找到匹配的结束标记 # + '-' * depth。"""
        while not await self._stream.eof():
            ch = await self._stream.current()
            assert ch is not None

            if ch == "#":
                await self._stream.advance()
                if await self._stream.eof():
                    break
                # 检查后续字符是否全是 '-'
                minus_count = 0
                while not await self._stream.eof() and await self._stream.current() == "-":
                    minus_count += 1
                    await self._stream.advance()
                if minus_count == depth:
                    return
                continue

            await self._stream.advance()

        self._errors.add(
            UnterminatedCommentError(self._current_source_info(), flag="#" + "+" * depth),
        )

    # ── 单字符 token ──────────────────────────────────
    async def _single_char(self, token_type: RawTokenType) -> RawToken:
        ch = await self._stream.current()
        assert ch is not None
        start = self._current_source_info()
        await self._stream.advance()
        return self._make_token(token_type, ch, start=start)

    # ── 单行字符串 ────────────────────────────────────

    async def _read_string(self) -> RawToken:
        """读取双引号包裹的单行字符串"""
        start = self._current_source_info()
        raw_parts: list[str] = [await self._stream.advance()]  # 消费 '"'

        while not await self._stream.eof():
            ch = await self._stream.current()
            assert ch is not None

            if ch == "\\":
                raw_parts.append(await self._stream.advance())
                if await self._stream.eof():
                    self._errors.add(UnterminatedStringError(
                        str_type=RawTokenType.STRING,
                        source=start,
                    ))
                    return self._make_token(RawTokenType.STRING, "".join(raw_parts), start=start)
                raw_parts.append(await self._stream.advance())
                continue

            if ch == '"':
                raw_parts.append(ch)
                await self._stream.advance()
                return self._make_token(RawTokenType.STRING, "".join(raw_parts), start=start)

            if ch == "\n":
                self._errors.add(UnterminatedStringError(
                    str_type=RawTokenType.STRING,
                    source=start,
                ))
                return self._make_token(RawTokenType.STRING, "".join(raw_parts), start=start)

            raw_parts.append(ch)
            await self._stream.advance()

        self._errors.add(UnterminatedStringError(
            str_type=RawTokenType.STRING,
            source=start
        ))
        raw_parts.append('"')  # 补上缺失的结束引号
        return self._make_token(RawTokenType.STRING, "".join(raw_parts), start=start)

    # ── 多行字符串（Markdown 风格） ────────────────────

    async def _read_multiline_string(self) -> RawToken:
        """读取反引号包裹的多行字符串。

        语法: `...`
        - 起始 ` 可变长（>= 1 个反引号）
        """
        start = self._current_source_info()

        # 统计起始反引号数量
        backtick_count = 0
        while not await self._stream.eof():
            ch = await self._stream.current()
            if ch == "`":
                backtick_count += 1
                await self._stream.advance()
            else:
                break

        # 读取内容直到匹配的结束反引号
        raw = "`" * backtick_count
        while not await self._stream.eof():
            ch = await self._stream.current()
            assert ch is not None

            if ch == "`":
                # 检查是否有足够的反引号匹配
                temp_count = 0
                while not await self._stream.eof() and await self._stream.current() == "`":
                    temp_count += 1
                    await self._stream.advance()
                if temp_count >= backtick_count:
                    raw += "`" * temp_count
                    return self._make_token(RawTokenType.MULTILINE_STRING, raw, start=start)
                else:
                    raw += "`" * temp_count
                    continue

            raw += ch
            await self._stream.advance()


        self._errors.add(UnterminatedStringError(
            str_type=RawTokenType.MULTILINE_STRING,
            source=start
        ))
        raw += "`" * backtick_count
        return self._make_token(RawTokenType.MULTILINE_STRING, raw, start=start)

    # ── 数字 / 特殊浮点字面量 ─────────────────────────

    async def _read_number_fallback(self) -> RawToken:
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
        ch = await self._stream.current()
        if ch is not None and ch in "+-":
            raw_parts.append(ch)
            await self._stream.advance()

        # ── 检查是否为特殊字面量 ──
        if raw_parts and raw_parts[0] in "+-":
            ch = await self._stream.current()
            if ch is not None and ch.isalpha():
                # 尝试读取标识符 (如 +inf, -inf)
                ident_parts: list[str] = []
                while not await self._stream.eof():
                    c = await self._stream.current()
                    if c is not None and (c.isalnum() or c == "_"):
                        ident_parts.append(c)
                        await self._stream.advance()
                    else:
                        break
                ident = "".join(ident_parts)
                full = raw_parts[0] + ident
                if full == "+inf":
                    return self._make_token(RawTokenType.FLOAT, full, start=start)
                if full == "-inf":
                    return self._make_token(RawTokenType.FLOAT, full, start=start)
                self._errors.add(InvalidNumberError(
                    raw=full,
                    source=start
                ))
                return self._make_token(RawTokenType.IDENTIFIER, full, start=start)

        # ── 2. 整数部分 ──
        ch = await self._stream.current()
        if ch is not None and ch.isdigit():
            raw_parts.append(ch)
            await self._stream.advance()
            while not await self._stream.eof():
                ch = await self._stream.current()
                if ch is not None and ch.isdigit():
                    raw_parts.append(ch)
                    await self._stream.advance()
                else:
                    break

        # ── 3. 可选小数部分 ──
        ch = await self._stream.current()
        if ch == ".":
            await self._stream.advance()  # 消费 '.'
            if not await self._stream.eof():
                next_ch = await self._stream.current()
                if next_ch is not None and next_ch.isdigit():
                    is_float = True
                    raw_parts.append(".")
                    raw_parts.append(next_ch)
                    await self._stream.advance()
                    while not await self._stream.eof():
                        ch = await self._stream.current()
                        if ch is not None and ch.isdigit():
                            raw_parts.append(ch)
                            await self._stream.advance()
                        else:
                            break
                else:
                    # 有前置数字但 . 后无数字 (如 "42.") → 记录错误
                    self._errors.add(
                        InvalidNumberError(
                            raw="".join(raw_parts) + ".",
                            source=start
                        )
                    )

        # ── 4. 可选指数部分 ──
        ch = await self._stream.current()
        if ch is not None and ch in ['e', 'E']:
            raw_parts.append(ch)
            await self._stream.advance()
            is_float = True

            if not await self._stream.eof():
                ch = await self._stream.current()
                if ch is not None and ch in "+-":
                    raw_parts.append(ch)
                    await self._stream.advance()

            if await self._stream.eof():
                self._errors.add(
                    InvalidNumberError(
                        raw="".join(raw_parts),
                        source=start
                    )
                )
            else:
                ch = await self._stream.current()
                if ch is not None and ch.isdigit():
                    raw_parts.append(ch)
                    await self._stream.advance()
                    while not await self._stream.eof():
                        ch = await self._stream.current()
                        if ch is not None and ch.isdigit():
                            raw_parts.append(ch)
                            await self._stream.advance()
                        else:
                            break
                else:
                    self._errors.add(
                        InvalidNumberError(
                            raw="".join(raw_parts),
                            source=start
                        )
                    )

        # ── 5. 确保至少有一位数字 ──
        raw = "".join(raw_parts)
        if not any(c.isdigit() for c in raw):
            self._errors.add(
                InvalidNumberError(
                    raw="".join(raw_parts),
                    source=start
                )
            )

        token_type = RawTokenType.FLOAT if is_float else RawTokenType.INTEGER
        return self._make_token(token_type, raw, start=start)

    # ── 标识符 / 关键字 ───────────────────────────────

    async def _read_identifier_or_keyword(self) -> RawToken:
        """读取标识符，识别关键字。"""
        start = self._current_source_info()
        raw_parts: list[str] = []

        while not await self._stream.eof():
            ch = await self._stream.current()
            if ch is not None and (ch.isalnum() or ch == "_"):
                raw_parts.append(ch)
                await self._stream.advance()
            else:
                break

        raw = "".join(raw_parts)
        token_type = self._keywords_map.get(raw, RawTokenType.IDENTIFIER)
        return self._make_token(token_type, raw, start=start)
