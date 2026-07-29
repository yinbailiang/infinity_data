

from __future__ import annotations

from collections.abc import AsyncIterable
import json

from infinity_data.tokenizer.models import (
    AtToken,
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
    Token,
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
    """将 infd/inft 源码转为 Token 流（异步）。"""

    def __init__(
        self, source: AsyncIterable[str], file_path: str = "unknown"
    ) -> None:
        self._file_path: str = file_path
        self._stream: CharStream = CharStream(source)

    # ── 异步迭代器协议 ────────────────────────────────────

    def __aiter__(self) -> RawTokenizer:
        return self

    async def __anext__(self) -> RawToken:
        tok = await self.next()
        if tok.type is TokenType.EOF:
            raise StopAsyncIteration
        return tok

    # ── 公开接口 ──────────────────────────────────────────

    async def next(self) -> RawToken:
        """异步返回下一个 token，文件末尾始终返回 EOF token。"""
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
            "@": TokenType.AT,
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

        # 数字
        if ch.isdigit():
            return await self._read_number()

        # 标识符 / 关键字
        if ch.isalpha() or ch == "_":
            return await self._read_identifier_or_keyword()

        raise ValueError(
            f"[{self._file_path}:{self._line}:{self._col}] "
            f"未预期的字符: {ch!r}"
        )

    # ── 内部辅助方法 ──────────────────────────────────────

    @property
    def _line(self) -> int:
        return self._stream.line

    @property
    def _col(self) -> int:
        return self._stream.col

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
        """跳过空格、制表符、回车及注释（# 到行尾）。"""
        while not await self._stream.eof():
            ch = await self._stream.current()
            if ch in (" ", "\t", "\r"):
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
        """读取引号包裹的字符串，支持转义。"""
        start = self._stream.index
        raw_parts: list[str] = [await self._stream.advance()]

        while not await self._stream.eof():
            ch = await self._stream.current()
            assert ch is not None

            if ch == "\\":
                # 转义：吃掉反斜杠和下一个字符
                raw_parts.append(await self._stream.advance())
                if not await self._stream.eof():
                    raw_parts.append(await self._stream.advance())
                continue

            raw_parts.append(ch)

            if ch == '"':
                await self._stream.advance()  # 跳过结束引号
                return self._make_token(
                    TokenType.STRING, "".join(raw_parts), start_index=start
                )

            if ch == "\n":
                raise ValueError(
                    f"[{self._file_path}:{self._line}:{self._col}] "
                    "字符串字面量中不允许未转义的换行"
                )

            await self._stream.advance()

        raise ValueError(
            f"[{self._file_path}:{self._line}:{self._col}] 未闭合的字符串字面量"
        )

    async def _read_number(self) -> RawToken:
        """读取整数或浮点数。"""
        start = self._stream.index
        raw_parts: list[str] = []
        is_float = False

        while not await self._stream.eof():
            ch = await self._stream.current()
            if ch is not None and ch.isdigit():
                raw_parts.append(ch)
                await self._stream.advance()
            elif ch == "." and not is_float:
                await self._stream.advance()
                if not await self._stream.eof():
                    next_ch = await self._stream.current()
                    if next_ch is not None and next_ch.isdigit():
                        is_float = True
                        raw_parts.append(".")
                        raw_parts.append(next_ch)
                        await self._stream.advance()
                    else:
                        break
                else:
                    break
            else:
                break

        raw = "".join(raw_parts)
        token_type = TokenType.FLOAT if is_float else TokenType.INTEGER
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
    TokenType.AT: AtToken,
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
    """将 RawToken 流转换为最终 Token 流（异步迭代器）。"""

    def __init__(self, source: AsyncIterable[RawToken]) -> None:
        self._source = source
        self._iter: AsyncIterable[RawToken] | None = None

    def __aiter__(self) -> FinalTokenizer:
        self._iter = self._source.__aiter__()
        return self

    async def __anext__(self) -> Token:
        assert self._iter is not None
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

