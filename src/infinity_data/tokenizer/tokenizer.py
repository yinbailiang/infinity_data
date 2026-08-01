from __future__ import annotations

import json
from collections.abc import AsyncIterable

from infinity_data.tokenizer.models import (
    ColonToken,
    CommaToken,
    EofToken,
    EqualsToken,
    ExclamationToken,
    ExistToken,
    FalseToken,
    FloatToken,
    FromToken,
    IdentifierToken,
    ImportToken,
    IntegerToken,
    LangleToken,
    LbraceToken,
    LbracketToken,
    LparenToken,
    NewlineToken,
    NullToken,
    QuestionToken,
    RangleToken,
    RawToken,
    RbraceToken,
    RbracketToken,
    RparenToken,
    SourceInfo,
    StringToken,
    TildeToken,
    Token,
    TokenizeErrorCollector,
    TokenType,
    TrueToken,
)
from infinity_data.tokenizer.stream import CharStream

# 关键字 -> TokenType 映射
_KEYWORDS: dict[str, TokenType] = {
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "null": TokenType.NULL,
    "exist": TokenType.EXIST,
    "import": TokenType.IMPORT,
    "from": TokenType.FROM,
}


class RawTokenizer:
    """将 infd/inft 源码转为 Token 流"""

    def __init__(
        self,
        source: AsyncIterable[str],
        file_path: str = "unknown",
        error_collector: TokenizeErrorCollector | None = None,
    ) -> None:
        self._file_path: str = file_path
        self._stream: CharStream = CharStream(source)
        self._errors: TokenizeErrorCollector = error_collector or TokenizeErrorCollector()

    # ── 异步迭代器协议 ────────────────────────────────────

    def __aiter__(self) -> RawTokenizer:
        return self

    async def __anext__(self) -> RawToken:
        tok = await self.next()
        if tok.type is TokenType.EOF:
            raise StopAsyncIteration
        return tok

    # ── 公开接口 ──────────────────────────────────────────

    @property
    def error_collector(self) -> TokenizeErrorCollector:
        """返回错误收集器，供外部查询本阶段是否有错误。"""
        return self._errors

    async def next(self) -> RawToken:
        """异步返回下一个 token，文件末尾始终返回 EOF token。

        遇到无法识别的字符时记录错误并跳过，继续尝试生成有效 token。
        """
        while True:
            await self._skip_whitespace_and_comments()

            if await self._stream.eof():
                return self._make_token(TokenType.EOF, "")

            ch = await self._stream.current()
            assert ch is not None

            # 单字符 token
            single_char_map: dict[str, TokenType] = {
                "{": TokenType.LBRACE,
                "}": TokenType.RBRACE,
                "[": TokenType.LBRACKET,
                "]": TokenType.RBRACKET,
                "(": TokenType.LPAREN,
                ")": TokenType.RPAREN,
                "<": TokenType.LANGLE,
                ">": TokenType.RANGLE,
                "=": TokenType.EQUALS,
                ":": TokenType.COLON,
                ",": TokenType.COMMA,
                "~": TokenType.TILDE,
                "!": TokenType.EXCLAMATION,
                "?": TokenType.QUESTION,
            }
            if ch in single_char_map:
                return await self._single_char(single_char_map[ch])

            # 换行
            if ch == "\n":
                return await self._handle_newline()

            # 字符串
            if ch == '"':
                return await self._read_string()

            # 数字（支持：正负号、前置小数点、科学计数法）
            if ch.isdigit() or ch in "+-.":
                return await self._read_number()

            # 标识符 / 关键字
            if ch.isalpha() or ch == "_":
                return await self._read_identifier_or_keyword()

            # 无法识别的字符 → 记录错误，跳过，继续
            self._errors.add(
                f"未预期的字符: {ch!r}",
                self._current_source_info(),
            )
            await self._stream.advance()
            # 继续循环，尝试下一个字符

    # ── 内部辅助方法 ──────────────────────────────────────

    @property
    def _line(self) -> int:
        return self._stream.line

    @property
    def _col(self) -> int:
        return self._stream.col

    def _current_source_info(self) -> SourceInfo:
        """构造当前位置的 SourceInfo。"""
        return SourceInfo(
            file=self._file_path,
            line=self._stream.line,
            col=self._stream.col,
            start=self._stream.index,
            end=self._stream.index,
        )

    def _make_token(
        self, token_type: TokenType, raw: str, start_index: int | None = None
    ) -> RawToken:
        """构造 RawToken，自动填充 SourceInfo。"""
        start = start_index if start_index is not None else self._stream.index
        return RawToken(
            type=token_type,
            raw=raw,
            source=SourceInfo(
                file=self._file_path,
                line=self._stream.line,
                col=self._stream.col,
                start=start,
                end=self._stream.index,
            ),
        )

    async def _skip_whitespace_and_comments(self) -> None:
        """跳过空白字符（除换行外）及注释（# 到行尾）。
        """
        while not await self._stream.eof():
            ch = await self._stream.current()
            # 跳过除换行外的所有 Unicode 空白字符
            assert ch is not None
            if ch != "\n" and ch.isspace():
                await self._stream.advance()
                continue
            if ch == "#":
                # 跳过注释直到换行或文件末尾
                while not await self._stream.eof() and await self._stream.current() != "\n":
                    await self._stream.advance()
                continue
            break

    async def _single_char(self, token_type: TokenType) -> RawToken:
        """处理单字符 token。"""
        ch = await self._stream.current()
        assert ch is not None
        start = self._stream.index
        await self._stream.advance()
        return self._make_token(token_type, ch, start_index=start)

    async def _handle_newline(self) -> RawToken:
        """处理换行 token。"""
        start = self._stream.index
        await self._stream.advance()
        return self._make_token(TokenType.NEWLINE, "\n", start_index=start)

    async def _read_string(self) -> RawToken:
        """读取引号包裹的字符串，支持转义。

        容错：
        - 未转义换行：记录错误，结束当前字符串（不消费换行符）。
        - 转义符后 EOF：记录错误，结束当前字符串。
        - 未闭合字符串（EOF）：记录错误，返回已读取的内容。
        """
        start = self._stream.index
        raw_parts: list[str] = [await self._stream.advance()]  # 消费 '"'

        while not await self._stream.eof():
            ch = await self._stream.current()
            assert ch is not None

            if ch == "\\":
                # 转义：吃掉反斜杠
                raw_parts.append(await self._stream.advance())
                if await self._stream.eof():
                    # 转义符后 EOF
                    self._errors.add(
                        "字符串中的转义符 '\\' 后缺少字符（遇到文件末尾）",
                        self._current_source_info(),
                    )
                    return self._make_token(
                        TokenType.STRING, "".join(raw_parts), start_index=start
                    )
                # 吃掉被转义的字符
                raw_parts.append(await self._stream.advance())
                continue

            if ch == '"':
                # 正常闭合
                raw_parts.append(ch)
                await self._stream.advance()
                return self._make_token(
                    TokenType.STRING, "".join(raw_parts), start_index=start
                )

            if ch == "\n":
                # 未转义换行 → 记录错误，结束字符串（不消费换行符）
                self._errors.add(
                    "字符串字面量中不允许未转义的换行",
                    self._current_source_info(),
                )
                return self._make_token(
                    TokenType.STRING, "".join(raw_parts), start_index=start
                )

            # 普通字符
            raw_parts.append(ch)
            await self._stream.advance()

        # EOF 但字符串未闭合
        self._errors.add(
            "未闭合的字符串字面量（遇到文件末尾）",
            self._current_source_info(),
        )
        return self._make_token(
            TokenType.STRING, "".join(raw_parts), start_index=start
        )

    async def _read_number(self) -> RawToken:
        """读取数字字面量。

        支持的格式（有序）：
            [+|-] 整数部分 [. 小数部分] [e|E [+|-] 指数]

        示例：42  -80  +3.14  .5  1e10  2.5e-3  -1.5E+2

        容错：
        - 只有符号或点号没有数字时记录错误
        - '.' 后没有数字时记录错误
        - 'e'/'E' 后没有指数时记录错误
        """
        start = self._stream.index
        raw_parts: list[str] = []
        is_float = False

        # ── 1. 可选正负号 ──
        ch = await self._stream.current()
        if ch is not None and ch in "+-":
            raw_parts.append(ch)
            await self._stream.advance()

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
            raw_parts.append(".")
            if await self._stream.eof():
                self._errors.add(
                    "数字字面量中 '.' 后缺少数字（遇到文件末尾）",
                    self._current_source_info(),
                )
            else:
                next_ch = await self._stream.current()
                if next_ch is not None and next_ch.isdigit():
                    is_float = True
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
                    self._errors.add(
                        f"数字字面量中 '.' 后缺少数字，遇到了 {next_ch!r}",
                        self._current_source_info(),
                    )

        # ── 4. 可选指数部分 ──
        ch = await self._stream.current()
        if ch is not None and ch in "eE":
            raw_parts.append(ch)
            await self._stream.advance()  # 消费 'e' 或 'E'
            is_float = True

            # 可选指数正负号
            if not await self._stream.eof():
                ch = await self._stream.current()
                if ch is not None and ch in "+-":
                    raw_parts.append(ch)
                    await self._stream.advance()

            # 指数必须有至少一位数字
            if await self._stream.eof():
                self._errors.add(
                    "科学计数法中 'e' 后缺少指数（遇到文件末尾）",
                    self._current_source_info(),
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
                        f"科学计数法中 'e' 后缺少指数，遇到了 {ch!r}",
                        self._current_source_info(),
                    )

        # ── 5. 确保至少有一位数字（拒绝孤立的 +/-/. 或 +e 之类）──
        raw = "".join(raw_parts)
        if not any(c.isdigit() for c in raw):
            self._errors.add(
                f"无效的数字字面量: {raw!r}（缺少数字）",
                self._current_source_info(),
            )

        token_type: TokenType = TokenType.FLOAT if is_float else TokenType.INTEGER
        return self._make_token(token_type, raw, start_index=start)

    async def _read_identifier_or_keyword(self) -> RawToken:
        """读取标识符，识别关键字。"""
        start = self._stream.index
        raw_parts: list[str] = []

        while not await self._stream.eof():
            ch = await self._stream.current()
            if ch is not None and (ch.isalnum() or ch == "_"):
                raw_parts.append(ch)
                await self._stream.advance()
            else:
                break

        raw = "".join(raw_parts)
        token_type = _KEYWORDS.get(raw, TokenType.IDENTIFIER)
        return self._make_token(token_type, raw, start_index=start)


# TokenType → Token 子类的映射
_TOKEN_CLASS_MAP: dict[TokenType, type[Token]] = {
    TokenType.LBRACE: LbraceToken,
    TokenType.RBRACE: RbraceToken,
    TokenType.LBRACKET: LbracketToken,
    TokenType.RBRACKET: RbracketToken,
    TokenType.LPAREN: LparenToken,
    TokenType.RPAREN: RparenToken,
    TokenType.LANGLE: LangleToken,
    TokenType.RANGLE: RangleToken,
    TokenType.EQUALS: EqualsToken,
    TokenType.COLON: ColonToken,
    TokenType.COMMA: CommaToken,
    TokenType.TILDE: TildeToken,
    TokenType.EXCLAMATION: ExclamationToken,
    TokenType.QUESTION: QuestionToken,
    TokenType.TRUE: TrueToken,
    TokenType.FALSE: FalseToken,
    TokenType.NULL: NullToken,
    TokenType.EXIST: ExistToken,
    TokenType.IMPORT: ImportToken,
    TokenType.FROM: FromToken,
    TokenType.NEWLINE: NewlineToken,
    TokenType.EOF: EofToken,
}


def _unescape_string(raw: str) -> str:
    """去除首尾引号并处理转义字符。"""
    return str(json.loads(raw))


class FinalTokenizer:
    """将 RawToken 流转换为最终 Token 流（异步迭代器）。

    跨阶段快速失败：如果传入的 ErrorCollector 中已有错误，
    则直接产生空 token 流，不再进行转换。
    """

    def __init__(
        self,
        source: AsyncIterable[RawToken],
        error_collector: TokenizeErrorCollector | None = None,
    ) -> None:
        self._source = source
        self._iter: AsyncIterable[RawToken] | None = None
        self._errors: TokenizeErrorCollector | None = error_collector

    def __aiter__(self) -> FinalTokenizer:
        self._iter = self._source.__aiter__()
        return self

    async def __anext__(self) -> Token:
        assert self._iter is not None

        # 跨阶段快速失败：前一阶段有错误时，不产生任何 token
        if self._errors is not None and self._errors.has_errors:
            raise StopAsyncIteration

        try:
            raw: RawToken = await self._iter.__anext__()  # type: ignore
            assert isinstance(raw, RawToken)
        except StopAsyncIteration:
            raise

        match raw.type:
            case TokenType.STRING:
                return StringToken(
                    source=raw.source, value=_unescape_string(raw.raw)
                )
            case TokenType.INTEGER:
                return IntegerToken(source=raw.source, value=int(raw.raw))
            case TokenType.FLOAT:
                return FloatToken(source=raw.source, value=float(raw.raw))
            case TokenType.IDENTIFIER:
                return IdentifierToken(source=raw.source, name=raw.raw)
            case _:
                token_cls = _TOKEN_CLASS_MAP[raw.type]
                return token_cls(type=raw.type, source=raw.source)

