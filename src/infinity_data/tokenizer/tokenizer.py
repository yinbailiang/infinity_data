"""InfinityData 词法分析器。

基于 neo_desg.md 重新设计的双阶段 tokenizer：
- RawTokenizer: 字符 → RawToken 流（容错，收集错误）
- FinalTokenizer: RawToken 流 → 最终 Token 流（转换字面量值）

新支持：
- 多行注释 (#+ ... #-)
- Markdown 风格多行字符串 (```` ```text ... ````)
- $ 导入命名空间引用前缀
- 特殊字面量: nan, +inf, -inf, noexist
- 导入关键字: env, file, as
- 逻辑约束关键字: not, any, one, all
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable

from infinity_data.tokenizer.models import (
    KEYWORDS,
    FloatToken,
    IdentifierToken,
    IntegerToken,
    MultilineStringToken,
    RawToken,
    SourceInfo,
    StringToken,
    Token,
    TokenizeErrorCollector,
    TokenType,
    make_final_token,
)
from infinity_data.tokenizer.stream import CharStream

# ═══════════════════════════════════════════════════════════
# RawTokenizer —— 阶段 1：字符 → RawToken
# ═══════════════════════════════════════════════════════════

class RawTokenizer:
    """将 infd/inft 源码转为 RawToken 流。"""

    def __init__(
        self,
        source: AsyncIterable[str],
        file_path: str = "unknown",
        error_collector: TokenizeErrorCollector | None = None,
    ) -> None:
        self._file_path: str = file_path
        self._stream: CharStream = CharStream(source)
        self._errors: TokenizeErrorCollector = error_collector or TokenizeErrorCollector()

    # ── 异步迭代器协议 ────────────────────────────────

    def __aiter__(self) -> RawTokenizer:
        return self

    async def __anext__(self) -> RawToken:
        tok = await self.next()
        if tok.type is TokenType.EOF:
            raise StopAsyncIteration
        return tok

    # ── 公开接口 ──────────────────────────────────────

    @property
    def error_collector(self) -> TokenizeErrorCollector:
        return self._errors

    async def next(self) -> RawToken:
        """异步返回下一个 token。"""
        while True:
            await self._skip_whitespace_and_comments()

            if await self._stream.eof():
                return self._make_token(TokenType.EOF, "")

            ch = await self._stream.current()
            assert ch is not None

            # ── 单字符 token ──────────────────────────
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
                "$": TokenType.DOLLAR,
            }
            if ch in single_char_map:
                return await self._single_char(single_char_map[ch])

            # ── 换行 ──────────────────────────────────
            if ch == "\n":
                return await self._handle_newline()

            # ── 字符串（双引号单行） ──────────────────
            if ch == '"':
                return await self._read_string()

            # ── 多行字符串（反引号） ──────────────────
            if ch == "`":
                return await self._read_multiline_string()

            # ── 数字 / 特殊浮点字面量 ─────────────────
            if ch.isdigit() or ch in "+-":
                return await self._read_number_or_special()

            # 前置小数点数字：仅当 . 后紧跟数字才当浮点数处理
            if ch == ".":
                return await self._read_number_or_special()

            # ── 标识符 / 关键字 ───────────────────────
            if ch.isalpha() or ch == "_":
                return await self._read_identifier_or_keyword()

            # ── 无法识别的字符 ────────────────────────
            self._errors.add(
                f"未预期的字符: {ch!r}",
                self._current_source_info(),
            )
            await self._stream.advance()

    # ── 内部辅助 ──────────────────────────────────────

    def _current_source_info(self) -> SourceInfo:
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
                    "多行注释 '#+' 开始后未找到结束标记",
                    self._current_source_info(),
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
                    # 成功匹配结束标记
                    return
                # 不匹配，但在多行注释内部，继续跳过
                continue

            await self._stream.advance()

        self._errors.add(
            f"多行注释未闭合: 需要 '#{'-' * depth}' 但遇到文件末尾",
            self._current_source_info(),
        )

    # ── 单字符 token ──────────────────────────────────

    async def _single_char(self, token_type: TokenType) -> RawToken:
        ch = await self._stream.current()
        assert ch is not None
        start = self._stream.index
        await self._stream.advance()
        return self._make_token(token_type, ch, start_index=start)

    # ── 换行 ──────────────────────────────────────────

    async def _handle_newline(self) -> RawToken:
        start = self._stream.index
        await self._stream.advance()
        return self._make_token(TokenType.NEWLINE, "\n", start_index=start)

    # ── 单行字符串 ────────────────────────────────────

    async def _read_string(self) -> RawToken:
        """读取双引号包裹的单行字符串，JSON 风格转义。"""
        start = self._stream.index
        raw_parts: list[str] = [await self._stream.advance()]  # 消费 '"'

        while not await self._stream.eof():
            ch = await self._stream.current()
            assert ch is not None

            if ch == "\\":
                raw_parts.append(await self._stream.advance())
                if await self._stream.eof():
                    self._errors.add(
                        "字符串中的转义符 '\\' 后缺少字符（遇到文件末尾）",
                        self._current_source_info(),
                    )
                    return self._make_token(TokenType.STRING, "".join(raw_parts), start_index=start)
                raw_parts.append(await self._stream.advance())
                continue

            if ch == '"':
                raw_parts.append(ch)
                await self._stream.advance()
                return self._make_token(TokenType.STRING, "".join(raw_parts), start_index=start)

            if ch == "\n":
                self._errors.add(
                    "字符串字面量中不允许未转义的换行",
                    self._current_source_info(),
                )
                return self._make_token(TokenType.STRING, "".join(raw_parts), start_index=start)

            raw_parts.append(ch)
            await self._stream.advance()

        self._errors.add(
            "未闭合的字符串字面量（遇到文件末尾）",
            self._current_source_info(),
        )
        return self._make_token(TokenType.STRING, "".join(raw_parts), start_index=start)

    # ── 多行字符串（Markdown 风格） ────────────────────

    async def _read_multiline_string(self) -> RawToken:
        """读取反引号包裹的多行字符串。

        语法: ````text ... ````
        - 起始 `` 可变长（>= 3 个反引号）
        - 可选语言标注 tag
        - 起始符后的空白和换行会被丢弃
        - 结束符前的最后一个换行和空白会被丢弃
        """
        start = self._stream.index

        # 1. 统计起始反引号数量
        backtick_count = 0
        while not await self._stream.eof():
            ch = await self._stream.current()
            if ch == "`":
                backtick_count += 1
                await self._stream.advance()
            else:
                break

        if backtick_count < 3:
            self._errors.add(
                "多行字符串需要至少 3 个反引号起始",
                self._current_source_info(),
            )
            # 退化为普通反引号
            return self._make_token(TokenType.STRING, "`" * backtick_count, start_index=start)

        # 2. 读取可选的语言标注 tag（直到行尾）
        tag = ""
        while not await self._stream.eof():
            ch = await self._stream.current()
            if ch == "\n":
                break
            tag += ch
            await self._stream.advance()
        tag = tag.strip()

        # 3. 跳过起始符后的空白行和行内空白
        if not await self._stream.eof():
            ch = await self._stream.current()
            if ch == "\n":
                await self._stream.advance()  # 跳过换行

        # 4. 读取内容直到匹配的结束反引号
        content_parts: list[str] = []
        while not await self._stream.eof():
            ch = await self._stream.current()
            assert ch is not None

            if ch == "`":
                # 尝试匹配结束标记
                _saved_pos = self._stream.index
                end_count = 0
                while not await self._stream.eof() and await self._stream.current() == "`":
                    end_count += 1
                    await self._stream.advance()
                if end_count == backtick_count:
                    # 成功匹配结束标记
                    # 构建原始字符串
                    raw = "`" * backtick_count + tag + "\n" + "".join(content_parts)
                    # 去除尾部空白和换行
                    content = "".join(content_parts)
                    # 如果内容以换行结尾，去掉最后一次换行及之后的空白
                    idx = len(content)
                    while idx > 0 and content[idx - 1] in " \t":
                        idx -= 1
                    if idx > 0 and content[idx - 1] == "\n":
                        idx -= 1
                    content = content[:idx]
                    return RawToken(
                        type=TokenType.MULTILINE_STRING,
                        raw=raw,
                        source=SourceInfo(
                            file=self._file_path,
                            line=self._stream.line,
                            col=self._stream.col,
                            start=start,
                            end=self._stream.index,
                        ),
                    )
                else:
                    # 不匹配：把反引号放回内容
                    content_parts.append("`" * end_count)
                    continue

            content_parts.append(ch)
            await self._stream.advance()

        self._errors.add(
            "未闭合的多行字符串（遇到文件末尾）",
            self._current_source_info(),
        )
        raw = "`" * backtick_count + tag + "\n" + "".join(content_parts)
        return self._make_token(TokenType.MULTILINE_STRING, raw, start_index=start)

    # ── 数字 / 特殊浮点字面量 ─────────────────────────

    async def _read_number_or_special(self) -> RawToken:
        """读取数字或特殊浮点字面量（nan, +inf, -inf）。

        支持的格式：
        - 整数: 42, -80
        - 浮点: 3.14, .5, 1e10, 2.5e-3
        - 特殊: nan, +inf, -inf
        """
        start = self._stream.index

        ch = await self._stream.current()
        assert ch is not None

        # ── 检查特殊浮点字面量前缀 ──
        if ch in "+-":
            await self._stream.advance()

        # 先按数字路径读取
        return await self._read_number_fallback(start)

    async def _read_number_fallback(self, start: int) -> RawToken:
        """读取数字字面量，支持特殊浮点字面量。"""
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
                    return self._make_token(TokenType.POS_INF, full, start_index=start)
                if full == "-inf":
                    return self._make_token(TokenType.NEG_INF, full, start_index=start)
                self._errors.add(
                    f"无效的数字字面量: {full!r}",
                    self._current_source_info(),
                )
                return self._make_token(TokenType.IDENTIFIER, full, start_index=start)

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
                    # . 后非数字 → 不是数字字面量
                    # 如果完全没有数字部分，产生一个标识符 token "."
                    if not raw_parts:
                        return self._make_token(
                            TokenType.IDENTIFIER, ".", start_index=start
                        )
                    # 有前置数字但 . 后无数字 (如 "42.") → 记录错误
                    self._errors.add(
                        f"数字字面量中 '.' 后缺少数字，遇到了 {next_ch!r}",
                        self._current_source_info(),
                    )
            else:
                # . 在文件末尾，且无前置数字 → 不是数字
                if not raw_parts:
                    return self._make_token(
                        TokenType.IDENTIFIER, ".", start_index=start
                    )
                self._errors.add(
                    "数字字面量中 '.' 后缺少数字（遇到文件末尾）",
                    self._current_source_info(),
                )

        # ── 4. 可选指数部分 ──
        ch = await self._stream.current()
        if ch is not None and ch in "eE":
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

        # ── 5. 确保至少有一位数字 ──
        raw = "".join(raw_parts)
        if not any(c.isdigit() for c in raw):
            self._errors.add(
                f"无效的数字字面量: {raw!r}（缺少数字）",
                self._current_source_info(),
            )

        token_type = TokenType.FLOAT if is_float else TokenType.INTEGER
        return self._make_token(token_type, raw, start_index=start)

    # ── 标识符 / 关键字 ───────────────────────────────

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
        # 检查关键字
        token_type = KEYWORDS.get(raw, TokenType.IDENTIFIER)
        return self._make_token(token_type, raw, start_index=start)


# ═══════════════════════════════════════════════════════════
# FinalTokenizer —— 阶段 2：RawToken → FinalToken
# ═══════════════════════════════════════════════════════════

def _unescape_string(raw: str) -> str:
    """去除首尾引号并处理 JSON 风格转义。"""
    return str(json.loads(raw))


def _unescape_multiline_string(raw: str, backtick_count: int, tag: str) -> tuple[str, str]:
    """处理多行字符串 raw 文本，提取内容和 tag。

    raw 格式: `<backtick_count>` + tag + "\n" + content
    已由 RawTokenizer 处理好尾部空白。

    返回: (content, tag)
    """
    # 跳过起始反引号和 tag
    prefix = "`" * backtick_count + tag
    if raw.startswith(prefix):
        content = raw[len(prefix):]
    else:
        content = raw[backtick_count:]

    # 跳过起始换行
    if content.startswith("\n"):
        content = content[1:]

    return content, tag


class FinalTokenizer:
    """将 RawToken 流转换为最终 Token 流。"""

    def __init__(
        self,
        source: AsyncIterable[RawToken],
        error_collector: TokenizeErrorCollector | None = None,
    ) -> None:
        self._source = source
        self._aiter: AsyncIterable[RawToken] | None = None
        self._errors: TokenizeErrorCollector | None = error_collector

    def __aiter__(self) -> FinalTokenizer:
        self._aiter = self._source.__aiter__()
        return self

    async def __anext__(self) -> Token:
        assert self._aiter is not None

        # 跨阶段快速失败
        if self._errors is not None and self._errors.has_errors:
            raise StopAsyncIteration

        try:
            raw: RawToken = await self._aiter.__anext__()  # type: ignore[assignment]
        except StopAsyncIteration:
            raise

        match raw.type:
            case TokenType.STRING:
                return StringToken(type=raw.type, source=raw.source, value=_unescape_string(raw.raw))
            case TokenType.MULTILINE_STRING:
                backtick_count = 0
                for ch in raw.raw:
                    if ch == "`":
                        backtick_count += 1
                    else:
                        break
                after_ticks = raw.raw[backtick_count:]
                tag = ""
                newline_idx = after_ticks.find("\n")
                if newline_idx >= 0:
                    tag = after_ticks[:newline_idx].strip()
                content, _ = _unescape_multiline_string(raw.raw, backtick_count, tag)
                return MultilineStringToken(type=raw.type, source=raw.source, value=content, tag=tag)
            case TokenType.INTEGER:
                return IntegerToken(type=raw.type, source=raw.source, value=int(raw.raw))
            case TokenType.FLOAT:
                return FloatToken(type=raw.type, source=raw.source, value=float(raw.raw))
            case TokenType.IDENTIFIER:
                return IdentifierToken(type=raw.type, source=raw.source, name=raw.raw)
            case _:
                return make_final_token(raw.type, raw.source)

