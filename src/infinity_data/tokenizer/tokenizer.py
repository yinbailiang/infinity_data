"""词法分析器"""

from infinity_data.infra.diagnostics import Diagnostic, DiagnosticCollector, Severity
from infinity_data.infra.file import File
from infinity_data.infra.ll1_stream import NoNextType
from infinity_data.tokenizer.char_stream import CharStream
from infinity_data.tokenizer.diagnostics import diag
from infinity_data.tokenizer.models.raw_tokens import (
    RawToken,
    RawTokenType,
    SourceInfo,
    SourceRange,
)


def _is_ascii_letter(ch: str) -> bool:
    """ASCII 字母（标识符/关键字只允许 ASCII，规范 [A-Za-z_]）。"""
    return 'a' <= ch <= 'z' or 'A' <= ch <= 'Z'


def _is_ascii_digit(ch: str) -> bool:
    """ASCII 数字（数字字面量只允许 [0-9]）。"""
    return '0' <= ch <= '9'


def _is_ident_start(ch: str) -> bool:
    """标识符起始字符：字母或下划线。"""
    return _is_ascii_letter(ch) or ch == '_'


def _is_ident_char(ch: str) -> bool:
    """标识符组成字符：字母/数字/下划线。"""
    return _is_ascii_letter(ch) or _is_ascii_digit(ch) or ch == '_'


def _peek_char(stream: CharStream) -> str | None:
    """安全取当前字符：EOF 返回 None，否则返回字符（不消费）。"""
    if stream.eof():
        return None
    ch = stream.peek()
    assert not isinstance(ch, NoNextType)
    return ch


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
        # '.' 不在此：需识别 '...'（ELLIPSIS）与单点（DOT），见 _read_dot_or_ellipsis
        # '*' 不在此：需识别 '**'（DOUBLE_STAR）与单星（STAR），见 _read_star
        '\n': RawTokenType.NEWLINE,
    }

    _keywords_map: dict[str, RawTokenType] = {
        'null': RawTokenType.NULL,
        'noexist': RawTokenType.NOEXIST,
        'true': RawTokenType.BOOL,
        'false': RawTokenType.BOOL,
        'nan': RawTokenType.FLOAT,
    }

    _open_to_close: dict[str, str] = {
        '{': '}',
        '[': ']',
        '(': ')',
        '<': '>',
    }
    _close_to_open: dict[str, str] = {close: open_ for open_, close in _open_to_close.items()}

    _BANG_KEYWORDS: tuple[str, ...] = ('env', 'file', 'from', 'var')
    _BANG_KEYWORD_TO_TYPE: dict[str, RawTokenType] = {
        'env': RawTokenType.ENV_IMPORT,
        'file': RawTokenType.FILE_IMPORT,
        'from': RawTokenType.FROM_IMPORT,
        'var': RawTokenType.VAR_IMPORT,
    }

    def __init__(
        self,
        file: File,
        error_collector: DiagnosticCollector | None = None,
    ) -> None:
        self._file: File = file
        self._stream: CharStream = CharStream(file.chars())
        self._diagnostic_collector = error_collector if error_collector is not None else DiagnosticCollector()
        self._eof_sent: bool = False
        self._open_stack: list[tuple[str, SourceInfo]] = []
        self._detect_bom(self._stream, self._diagnostic_collector, self._file)

    @staticmethod
    def _detect_bom(stream: CharStream, collector: DiagnosticCollector, file: File) -> None:
        """检测文件 BOM（规范要求 UTF-8 NO BOM）：报 tokenize.bom 警告并跳过。"""
        if not stream.eof() and stream.peek() == '\ufeff':
            collector.add(
                Diagnostic(
                    Severity.WARNING,
                    'tokenize.bom',
                    {},
                    SourceRange.at(file, stream.info()),
                )
            )
            stream.advance()

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
    def diagnostic_collector(self) -> DiagnosticCollector:
        return self._diagnostic_collector

    @property
    def file(self) -> File:
        return self._file

    def next(self) -> RawToken:
        """返回下一个 token。"""
        stream = self._stream
        collector = self._diagnostic_collector
        file = self._file

        while True:
            self._skip_whitespace_and_comments(stream, collector, file)

            if stream.eof():
                self._report_unclosed_brackets(self._open_stack, collector, file)
                return self._make_token(RawTokenType.EOF, '', stream.info(), stream, file)

            ch = stream.peek()
            assert not isinstance(ch, NoNextType)

            if ch == '.':
                return self._read_dot_or_ellipsis(stream, file)

            if ch == '*':
                return self._read_star(stream, file)

            if ch in self._single_char_map:
                tok = self._single_char(self._single_char_map[ch], stream, file)
                self._track_bracket(ch, tok, self._open_stack, collector)
                return tok

            if ch == '!':
                tok = self._read_bang(stream, collector, file)
                if tok is not None:
                    return tok
                continue  # 词法错误已报，跳过该 ! 序列

            if ch == '"':
                return self._read_string(stream, collector, file)

            if ch == '`':
                return self._read_multiline_string(stream, collector, file)

            if _is_ascii_digit(ch) or ch in ['+', '-']:
                tok = self._read_number_fallback(stream, collector, file)
                if tok is not None:
                    return tok
                continue  # 非法数字序列已报错并跳过

            # ── 标识符 / 关键字 ───────────────────────
            if _is_ident_start(ch):
                return self._read_identifier_or_keyword(stream, file)

            # ── 无法识别的字符 ────────────────────────
            collector.add(diag('tokenize.unknown_char', {'char': ch}, SourceRange.at(file, stream.info())))
            stream.advance()

    @staticmethod
    def _make_token(
        token_type: RawTokenType,
        raw: str,
        start: SourceInfo,
        stream: CharStream,
        file: File,
    ) -> RawToken:
        return RawToken(
            type=token_type,
            raw=raw,
            source=SourceRange(
                file=file,
                start=start,
                end=stream.info(),
            ),
        )

    @staticmethod
    def _read_dot_or_ellipsis(stream: CharStream, file: File) -> RawToken:
        """读取 `.`（DOT，JSON path）或 `...`（ELLIPSIS，展开标记）。

        连续点数：1 → DOT；3 → ELLIPSIS；其他数量（2 / >=4）按 DOT 恢复
        （罕见错误场景，多余点由语法层报错）。
        """
        start = stream.info()
        count = 0
        while not stream.eof():
            ch = stream.peek()
            assert not isinstance(ch, NoNextType)
            if ch != '.':
                break
            stream.advance()
            count += 1
        if count == 3:
            return RawToken(
                type=RawTokenType.ELLIPSIS,
                raw='...',
                source=SourceRange(file=file, start=start, end=stream.info()),
            )
        return RawToken(
            type=RawTokenType.DOT,
            raw='.',
            source=SourceRange(file=file, start=start, end=stream.info()),
        )

    @staticmethod
    def _read_star(stream: CharStream, file: File) -> RawToken:
        """读取 `*`（STAR）或 `**`（DOUBLE_STAR）。"""
        start = stream.info()
        stream.advance()
        if not stream.eof():
            ch = stream.peek()
            assert not isinstance(ch, NoNextType)
            if ch == '*':
                stream.advance()
                return RawToken(
                    type=RawTokenType.DOUBLE_STAR,
                    raw='**',
                    source=SourceRange(file=file, start=start, end=stream.info()),
                )
        return RawToken(
            type=RawTokenType.STAR,
            raw='*',
            source=SourceRange(file=file, start=start, end=stream.info()),
        )

    # ── 空白与注释跳过 ────────────────────────────────

    @staticmethod
    def _skip_whitespace_and_comments(stream: CharStream, collector: DiagnosticCollector, file: File) -> None:
        """跳过空白及注释（单行 # 和多行 #+...#-）。"""
        while not stream.eof():
            ch = stream.peek()
            assert not isinstance(ch, NoNextType)

            # 跳过除换行外的空白
            if ch != '\n' and ch.isspace():
                stream.advance()
                continue

            # 单行注释: # 到行尾
            if ch == '#':
                RawTokenizer._handle_comment(stream, collector, file)
                continue

            break

    @staticmethod
    def _handle_comment(stream: CharStream, collector: DiagnosticCollector, file: File) -> None:
        """处理注释：单行 # 或多行 #+...#-"""
        stream.advance()  # 消费 '#'

        if stream.eof():
            return

        ch = stream.peek()
        assert not isinstance(ch, NoNextType)

        # 检查是否为多行注释起始标记 #+
        plus_count = 0
        while ch == '+':
            plus_count += 1
            stream.advance()
            if stream.eof():
                collector.add(
                    diag(
                        'tokenize.unterminated_comment',
                        {'flag': '#' + '-' * plus_count},
                        SourceRange.at(file, stream.info()),
                    )
                )
                return
            ch = stream.peek()
            assert not isinstance(ch, NoNextType)

        if plus_count > 0:
            # 多行注释模式: 需要找到匹配的 # + '-' * plus_count
            RawTokenizer._skip_multiline_comment(stream, collector, file, plus_count)
        else:
            # 单行注释: 跳到行尾
            while not stream.eof() and stream.peek() != '\n':
                stream.advance()

    @staticmethod
    def _skip_multiline_comment(stream: CharStream, collector: DiagnosticCollector, file: File, depth: int) -> None:
        """跳过多行注释直到找到匹配的结束标记 # + '-' * depth。"""
        while not stream.eof():
            ch = stream.peek()
            assert not isinstance(ch, NoNextType)

            if ch == '#':
                stream.advance()
                if stream.eof():
                    break
                # 检查后续字符是否全是 '-'
                minus_count = 0
                while not stream.eof() and stream.peek() == '-':
                    minus_count += 1
                    stream.advance()
                if minus_count == depth:
                    return
                continue

            stream.advance()

        collector.add(
            diag(
                'tokenize.unterminated_comment',
                {'flag': '#' + '-' * depth},
                SourceRange.at(file, stream.info()),
            )
        )

    # ── 单字符 token ──────────────────────────────────
    @staticmethod
    def _single_char(token_type: RawTokenType, stream: CharStream, file: File) -> RawToken:
        ch = stream.peek()
        assert not isinstance(ch, NoNextType)
        start = stream.info()
        stream.advance()
        return RawTokenizer._make_token(token_type, ch, start=start, stream=stream, file=file)

    # ── 括号栈（EOF 时报告未闭合）────────────────────
    @staticmethod
    def _track_bracket(
        ch: str,
        tok: RawToken,
        open_stack: list[tuple[str, SourceInfo]],
        collector: DiagnosticCollector,
    ) -> None:
        """维护括号栈并校验类型配对（开压闭弹）。

        - 开括号：压栈
        - 闭括号与栈顶配对：弹栈
        - 闭括号与栈顶不配对：报 ``tokenize.mismatched_bracket`` 并弹出栈顶（错误恢复）
        - 闭括号且栈为空：报 ``tokenize.unexpected_close_bracket``
        """
        if ch in RawTokenizer._open_to_close:
            open_stack.append((ch, tok.source.start))
        elif ch in RawTokenizer._close_to_open:
            if not open_stack:
                collector.add(diag('tokenize.unexpected_close_bracket', {'bracket': ch}, tok.source))
                return
            open_bracket, _ = open_stack[-1]
            if open_bracket == RawTokenizer._close_to_open[ch]:
                open_stack.pop()
            else:
                collector.add(
                    diag(
                        'tokenize.mismatched_bracket',
                        {'open': open_bracket, 'close': ch},
                        tok.source,
                    )
                )
                open_stack.pop()

    @staticmethod
    def _report_unclosed_brackets(
        open_stack: list[tuple[str, SourceInfo]],
        collector: DiagnosticCollector,
        file: File,
    ) -> None:
        """EOF 时仍开着的括号 → 报 tokenize.unterminated_bracket（按开括号顺序）。"""
        for bracket, start in open_stack:
            collector.add(diag('tokenize.unterminated_bracket', {'bracket': bracket}, SourceRange.at(file, start)))
        open_stack.clear()

    # ── ! 导入关键字（词法组合，! 无独立语法）──

    @staticmethod
    def _read_bang(stream: CharStream, collector: DiagnosticCollector, file: File) -> RawToken | None:
        """读取 ``!`` 起始的 token。

        - ``!env`` / ``!file`` / ``!from`` → 组合导入关键字 token
        - 其他任何情况 → 词法错误（语言不允许单独 ``!``），返回 None 跳过
        """
        start = stream.info()
        stream.advance()  # 消费 '!'

        if stream.eof():
            collector.add(diag('tokenize.invalid_bang', {'actual': 'EOF'}, SourceRange.at(file, start)))
            return None
        ch = stream.peek()
        assert not isinstance(ch, NoNextType)
        if not _is_ident_start(ch):
            collector.add(diag('tokenize.invalid_bang', {'actual': repr(ch)}, SourceRange.at(file, start)))
            stream.advance()  # 消费非法字符，避免下一轮重复处理（如 !@ 再报 unknown_char）
            return None

        ident_tok = RawTokenizer._read_identifier_or_keyword(stream, file)
        match ident_tok.raw:
            case 'env':
                return RawTokenizer._make_token(RawTokenType.ENV_IMPORT, '!env', start=start, stream=stream, file=file)
            case 'file':
                return RawTokenizer._make_token(
                    RawTokenType.FILE_IMPORT, '!file', start=start, stream=stream, file=file
                )
            case 'from':
                return RawTokenizer._make_token(
                    RawTokenType.FROM_IMPORT, '!from', start=start, stream=stream, file=file
                )
            case 'var':
                return RawTokenizer._make_token(RawTokenType.VAR_IMPORT, '!var', start=start, stream=stream, file=file)
            case _:
                return RawTokenizer._recover_bang_typo(ident_tok.raw, start, stream, collector, file)

    @staticmethod
    def _edit_distance(a: str, b: str) -> int:
        """计算两个字符串的编辑距离（Levenshtein：增/删/改各计 1）。"""
        la, lb = len(a), len(b)
        if la == 0:
            return lb
        if lb == 0:
            return la
        prev = list(range(lb + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(
                    min(
                        prev[j] + 1,  # 删除
                        cur[j - 1] + 1,  # 插入
                        prev[j - 1] + int(ca != cb),  # 替换
                    )
                )
            prev = cur
        return prev[lb]

    @staticmethod
    def _nearest_bang_keyword(actual: str) -> str | None:
        """返回与 actual 编辑距离 <= 1 的最近导入关键字，否则 None。"""
        best: str | None = None
        best_dist = 2  # 阈值：仅接受单字符增/删/改
        for keyword in RawTokenizer._BANG_KEYWORDS:
            dist = RawTokenizer._edit_distance(actual, keyword)
            if dist < best_dist:
                best_dist = dist
                best = keyword
        return best

    @staticmethod
    def _recover_bang_typo(
        actual: str,
        start: SourceInfo,
        stream: CharStream,
        collector: DiagnosticCollector,
        file: File,
    ) -> RawToken | None:
        """对 ! 后非关键字标识符做拼写纠正恢复。

        - 与 env/file/from 编辑距离 <= 1 → 报 ``tokenize.bang_corrected`` 并恢复为对应导入关键字；
        - 否则报 ``tokenize.invalid_bang`` 并返回 None（丢弃）。
        """
        suggestion = RawTokenizer._nearest_bang_keyword(actual)
        if suggestion is not None:
            collector.add(
                diag(
                    'tokenize.bang_corrected',
                    {'actual': actual, 'suggestion': suggestion},
                    SourceRange.at(file, start),
                )
            )
            return RawTokenizer._make_token(
                RawTokenizer._BANG_KEYWORD_TO_TYPE[suggestion],
                '!' + suggestion,
                start=start,
                stream=stream,
                file=file,
            )
        collector.add(diag('tokenize.invalid_bang', {'actual': repr(actual)}, SourceRange.at(file, start)))
        return None

    # ── 单行字符串 ────────────────────────────────────

    @staticmethod
    def _read_string(stream: CharStream, collector: DiagnosticCollector, file: File) -> RawToken:
        """读取双引号包裹的单行字符串"""
        start = stream.info()
        raw_parts: list[str] = [stream.advance()]  # 消费 '"'

        def close() -> None:
            """补全结束引号：若尾部是未完成的转义反斜杠则先丢弃，保证 raw 是合法 JSON 字符串。"""
            if raw_parts and raw_parts[-1] == '\\':
                raw_parts.pop()  # 丢弃未完成的转义反斜杠
            raw_parts.append('"')

        while not stream.eof():
            ch = stream.peek()
            assert not isinstance(ch, NoNextType)

            if ch == '\\':
                raw_parts.append(stream.advance())  # 消费反斜杠
                if stream.eof():
                    collector.add(diag('tokenize.unterminated_string', {}, SourceRange.at(file, start)))
                    close()
                    return RawTokenizer._make_token(
                        RawTokenType.STRING, ''.join(raw_parts), start=start, stream=stream, file=file
                    )
                nxt = stream.peek()
                assert not isinstance(nxt, NoNextType)
                if nxt == '\n':
                    # 单行字符串不允许真实换行（规范：json 风格转义）→ 与裸换行分支一致报错恢复
                    collector.add(diag('tokenize.unterminated_string', {}, SourceRange.at(file, start)))
                    close()
                    return RawTokenizer._make_token(
                        RawTokenType.STRING, ''.join(raw_parts), start=start, stream=stream, file=file
                    )
                raw_parts.append(stream.advance())
                continue

            if ch == '"':
                raw_parts.append(ch)
                stream.advance()
                return RawTokenizer._make_token(
                    RawTokenType.STRING, ''.join(raw_parts), start=start, stream=stream, file=file
                )

            if ch == '\n':
                collector.add(diag('tokenize.unterminated_string', {}, SourceRange.at(file, start)))
                close()
                return RawTokenizer._make_token(
                    RawTokenType.STRING, ''.join(raw_parts), start=start, stream=stream, file=file
                )

            raw_parts.append(ch)
            stream.advance()

        collector.add(diag('tokenize.unterminated_string', {}, SourceRange.at(file, start)))
        close()
        return RawTokenizer._make_token(RawTokenType.STRING, ''.join(raw_parts), start=start, stream=stream, file=file)

    # ── 多行字符串（Markdown 风格） ────────────────────

    @staticmethod
    def _read_multiline_string(stream: CharStream, collector: DiagnosticCollector, file: File) -> RawToken:
        """读取反引号包裹的多行字符串。

        语法: `...`
        - 起始 ` 可变长（>= 1 个反引号）
        """
        start = stream.info()

        # 统计起始反引号数量
        backtick_count = 0
        while not stream.eof():
            ch = stream.peek()
            if ch == '`':
                backtick_count += 1
                stream.advance()
            else:
                break

        # 读取内容直到匹配的结束反引号
        raw = '`' * backtick_count
        while not stream.eof():
            ch = stream.peek()
            assert not isinstance(ch, NoNextType)

            if ch == '`':
                # 检查是否有足够的反引号匹配
                temp_count = 0
                while temp_count < backtick_count and not stream.eof() and stream.peek() == '`':
                    temp_count += 1
                    stream.advance()
                if temp_count == backtick_count:
                    raw += '`' * temp_count
                    return RawTokenizer._make_token(
                        RawTokenType.MULTILINE_STRING, raw, start=start, stream=stream, file=file
                    )
                else:
                    raw += '`' * temp_count
                    continue

            raw += ch
            stream.advance()

        collector.add(
            diag(
                'tokenize.unterminated_multiline_string',
                {'flag': '`' * backtick_count},
                SourceRange.at(file, start),
            )
        )
        raw += '`' * backtick_count
        return RawTokenizer._make_token(RawTokenType.MULTILINE_STRING, raw, start=start, stream=stream, file=file)

    # ── 数字 / 特殊浮点字面量 ─────────────────────────

    @staticmethod
    def _read_number_fallback(stream: CharStream, collector: DiagnosticCollector, file: File) -> RawToken | None:
        """读取数字或特殊浮点字面量（nan, +inf, -inf, ±nan）。

        支持的格式：
        - 整数: 42, -80
        - 浮点: 3.14, 5.0, 1e10, 2.5e-3
        - 特殊: +inf, -inf（nan 由关键字路径处理）；+nan/-nan 合法但警告并归一化为 nan

        错误恢复：绝不产出非法 raw 的数值 token。
        - 残缺指数/小数（如 ``5e``、``5e+``、``42.``）→ 报错并补 ``0`` 恢复为合法浮点；
        - 完全没有合法数字（如 ``+``、``+foo``）→ 消费整个非法序列并返回 None。
        """
        start = stream.info()
        raw_parts: list[str] = []
        is_float = False

        def invalid(raw: str) -> None:
            collector.add(diag('tokenize.invalid_number', {'raw': raw}, SourceRange.at(file, start)))

        # ── 1. 可选正负号 ──
        ch = _peek_char(stream)
        if ch is not None and ch in '+-':
            raw_parts.append(ch)
            stream.advance()

        # ── 检查是否为特殊字面量（+inf / -inf / ±nan）──
        if raw_parts and raw_parts[0] in '+-':
            ch = _peek_char(stream)
            if ch is not None and _is_ident_start(ch):
                # 尝试读取标识符 (如 +inf, -inf)
                ident_parts: list[str] = []
                while not stream.eof():
                    c = _peek_char(stream)
                    if c is not None and _is_ident_char(c):
                        ident_parts.append(c)
                        stream.advance()
                    else:
                        break
                full = raw_parts[0] + ''.join(ident_parts)
                if full == '+inf':
                    return RawTokenizer._make_token(RawTokenType.FLOAT, full, start=start, stream=stream, file=file)
                if full == '-inf':
                    return RawTokenizer._make_token(RawTokenType.FLOAT, full, start=start, stream=stream, file=file)
                if full in ('+nan', '-nan'):
                    # 带符号 NaN：合法但警告，归一化为 nan（NaN 无符号）
                    collector.add(
                        Diagnostic(
                            Severity.WARNING,
                            'tokenize.signed_nan',
                            {'raw': full},
                            SourceRange.at(file, start),
                        )
                    )
                    return RawTokenizer._make_token(RawTokenType.FLOAT, 'nan', start=start, stream=stream, file=file)
                # 非法（如 +foo）：整个序列已消费，跳过，不留非法 token
                invalid(full)
                return None

        # ── 2. 整数部分 ──
        ch = _peek_char(stream)
        if ch is not None and _is_ascii_digit(ch):
            raw_parts.append(ch)
            stream.advance()
            while not stream.eof():
                ch = _peek_char(stream)
                if ch is not None and _is_ascii_digit(ch):
                    raw_parts.append(ch)
                    stream.advance()
                else:
                    break

        # ── 3. 可选小数部分 ──
        ch = _peek_char(stream)
        if ch == '.':
            stream.advance()  # 消费 '.'
            next_ch = _peek_char(stream)
            if next_ch is not None and _is_ascii_digit(next_ch):
                is_float = True
                raw_parts.append('.')
                raw_parts.append(next_ch)
                stream.advance()
                while not stream.eof():
                    ch = _peek_char(stream)
                    if ch is not None and _is_ascii_digit(ch):
                        raw_parts.append(ch)
                        stream.advance()
                    else:
                        break
            else:
                # . 后无数字（如 42. / 42.a）→ 报错并补 0 恢复为浮点
                invalid(''.join(raw_parts) + '.')
                raw_parts.extend(['.', '0'])
                is_float = True

        # ── 4. 可选指数部分 ──
        ch = _peek_char(stream)
        if ch is not None and ch in ['e', 'E']:
            stream.advance()  # 消费 'e'/'E'
            exponent_parts: list[str] = ['e']
            ch = _peek_char(stream)
            if ch is not None and ch in '+-':
                exponent_parts.append(ch)
                stream.advance()

            ch = _peek_char(stream)
            if ch is None:
                # 残缺指数（如 5e / 5e+）→ 报错并补 0 恢复为浮点
                invalid(''.join(raw_parts) + ''.join(exponent_parts))
                raw_parts.extend(exponent_parts)
                raw_parts.append('0')
                is_float = True
            elif _is_ascii_digit(ch):
                raw_parts.extend(exponent_parts)
                is_float = True
                raw_parts.append(ch)
                stream.advance()
                while not stream.eof():
                    ch = _peek_char(stream)
                    if ch is not None and _is_ascii_digit(ch):
                        raw_parts.append(ch)
                        stream.advance()
                    else:
                        break
            else:
                # 指数后非数字（如 5e+foo）→ 报错并补 0 恢复为浮点
                invalid(''.join(raw_parts) + ''.join(exponent_parts))
                raw_parts.extend(exponent_parts)
                raw_parts.append('0')
                is_float = True

        # ── 5. 确保至少有一位数字；否则跳过整个非法序列 ──
        raw = ''.join(raw_parts)
        if not any(_is_ascii_digit(c) for c in raw):
            invalid(raw)
            return None

        token_type = RawTokenType.FLOAT if is_float else RawTokenType.INTEGER
        return RawTokenizer._make_token(token_type, raw, start=start, stream=stream, file=file)

    # ── 标识符 / 关键字 ───────────────────────────────

    @staticmethod
    def _read_identifier_or_keyword(stream: CharStream, file: File) -> RawToken:
        """读取标识符，识别关键字。"""
        start = stream.info()
        raw_parts: list[str] = []

        while not stream.eof():
            ch = stream.peek()
            if not isinstance(ch, NoNextType) and _is_ident_char(ch):
                raw_parts.append(ch)
                stream.advance()
            else:
                break

        raw = ''.join(raw_parts)
        token_type = RawTokenizer._keywords_map.get(raw, RawTokenType.IDENTIFIER)
        return RawTokenizer._make_token(token_type, raw, start=start, stream=stream, file=file)
