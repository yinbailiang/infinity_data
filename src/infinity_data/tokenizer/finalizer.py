"""终遍词法分析器：将 RawToken 流转换为 Token 流。

职责：
- 解析转义序列（字符串）
- 提取多行字符串的 tags 并修剪空白
- 将字符串形式的数字解析为 Python 数值类型
- 区分特殊浮点字面量（nan, +inf, -inf）与普通浮点数
"""

from __future__ import annotations

import decimal
import json
from collections.abc import Iterable, Iterator

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.tokenizer.diagnostics import diag
from infinity_data.tokenizer.models.raw_tokens import (
    RawToken,
    RawTokenType,
)
from infinity_data.tokenizer.models.tokens import (
    BoolToken,
    ColonToken,
    CommaToken,
    DollarToken,
    DotToken,
    EnvImportToken,
    EofToken,
    EqualsToken,
    ExclamationToken,
    FileImportToken,
    FloatToken,
    FromImportToken,
    IdentifierToken,
    IntegerToken,
    LangleToken,
    LbraceToken,
    LbracketToken,
    LparenToken,
    MultilineStringToken,
    NewlineToken,
    NoexistToken,
    NullToken,
    QuestionToken,
    RangleToken,
    RbraceToken,
    RbracketToken,
    RparenToken,
    SinglelineStringToken,
    TildeToken,
    Token,
)

# ── 单字符 token 映射 ──────────────────────────────

_SIMPLE_MAP: dict[RawTokenType, type[Token]] = {
    RawTokenType.LBRACE: LbraceToken,
    RawTokenType.RBRACE: RbraceToken,
    RawTokenType.LBRACKET: LbracketToken,
    RawTokenType.RBRACKET: RbracketToken,
    RawTokenType.LPAREN: LparenToken,
    RawTokenType.RPAREN: RparenToken,
    RawTokenType.LANGLE: LangleToken,
    RawTokenType.RANGLE: RangleToken,
    RawTokenType.EQUALS: EqualsToken,
    RawTokenType.COLON: ColonToken,
    RawTokenType.COMMA: CommaToken,
    RawTokenType.TILDE: TildeToken,
    RawTokenType.EXCLAMATION: ExclamationToken,
    RawTokenType.QUESTION: QuestionToken,
    RawTokenType.DOLLAR: DollarToken,
    RawTokenType.DOT: DotToken,
    RawTokenType.NULL: NullToken,
    RawTokenType.NOEXIST: NoexistToken,
    RawTokenType.ENV_IMPORT: EnvImportToken,
    RawTokenType.FILE_IMPORT: FileImportToken,
    RawTokenType.FROM_IMPORT: FromImportToken,
    RawTokenType.NEWLINE: NewlineToken,
}


# ── 多行字符串处理 ─────────────────────────────────


def _process_multiline_string(raw: str) -> tuple[str, list[str]]:
    """处理多行字符串 raw 返回 (content, tags)。

    raw 格式: ```[tags]\n[content]```
    """
    # 1. 统计起始反引号数量
    backtick_count = 0
    for ch in raw:
        if ch == '`':
            backtick_count += 1
        else:
            break

    if backtick_count == 0:
        return raw, []

    # 2. 提取 tags（起始行剩余部分）
    rest_start: int = backtick_count
    newline_idx: int = raw.find('\n', rest_start)
    if newline_idx == -1:  # 无换行：整个同一行为 tags，无内容
        tags_part: str = raw[rest_start:]  # 排除结束围栏
        # 找到结束围栏位置（应从尾部去除 backtick_count 个反引号）
        if raw.endswith('`' * backtick_count):
            tags_part = raw[rest_start:-backtick_count]
        tags: list[str] = tags_part.split() if tags_part.strip() else []
        return '', tags

    tags_part = raw[rest_start:newline_idx]
    tags = tags_part.split() if tags_part.strip() else []

    # 3. 内容起始（跳过首换行）
    content_start = newline_idx + 1

    # 4. 查找结束反引号（从尾部反向扫描，跳过尾空白）
    closing_start: int | None = None
    # 从尾部查找连续反引号序列
    idx = len(raw) - 1
    while idx >= content_start:
        if raw[idx] == '`':
            # 向前数连续反引号
            seq_end = idx
            while idx >= content_start and raw[idx] == '`':
                idx -= 1
            seq_len = seq_end - idx
            if seq_len == backtick_count:
                closing_start = idx + 1
                break
        else:
            idx -= 1

    if closing_start is None:
        # 未找到匹配结束符（不应发生，RawTokenizer 已保证）
        content = raw[content_start:]
        return content.rstrip(), tags

    # 5. 内容在 content_start 到 closing_start 之间
    content = raw[content_start:closing_start]

    # 6. 丢弃尾部空白及一个格式化换行
    content: str = content.rstrip(' \t').removesuffix('\n')

    return content, tags


# ═══════════════════════════════════════════════════════════
# FinalTokenizer
# ═══════════════════════════════════════════════════════════


class FinalTokenizer:
    """终遍词法分析器：消费 RawToken 流，产出 Token 流。

    ``error_collector``：与 :class:`RawTokenizer` 同一收集器（词法层容错收集）——
    值转换失败（无效转义 / 无效数字）收集为诊断并产出恢复 token，**从不抛异常**。
    """

    def __init__(
        self,
        source: Iterable[RawToken],
        error_collector: DiagnosticCollector | None = None,
    ) -> None:
        self._iter: Iterator[RawToken] | None = None
        self._source: Iterable[RawToken] = source
        # 注意：不能用 `or` —— 空 DiagnosticCollector 的 __bool__ 为 False，会静默丢弃传入的收集器
        self._errors = error_collector if error_collector is not None else DiagnosticCollector()

    def __iter__(self) -> 'FinalTokenizer':
        return self

    def __next__(self) -> Token:
        if self._iter is None:
            self._iter = iter(self._source)
        raw = next(self._iter)
        return self._convert(raw)

    # ── 转换核心 ──────────────────────────────────────

    def _convert(self, raw: RawToken) -> Token:
        """将单个 RawToken 转换为对应的 Token 子类。"""
        token_type = raw.type

        # EOF
        if token_type == RawTokenType.EOF:
            return EofToken(raw=raw)

        # 简单映射（无需解析值）
        if token_type in _SIMPLE_MAP:
            return _SIMPLE_MAP[token_type](raw=raw)

        # 需要解析值的类型
        if token_type == RawTokenType.STRING:
            return self._convert_string(raw)

        if token_type == RawTokenType.MULTILINE_STRING:
            return self._convert_multiline_string(raw)

        if token_type == RawTokenType.INTEGER:
            return self._convert_integer(raw)

        if token_type == RawTokenType.FLOAT:
            return self._convert_float(raw)

        if token_type == RawTokenType.BOOL:
            return self._convert_bool(raw)

        if token_type == RawTokenType.IDENTIFIER:
            return IdentifierToken(raw=raw, name=raw.raw)

        # 未知类型（不应到达）
        raise ValueError(f'未知 RawTokenType: {token_type}')

    # ── 各类型转换 ────────────────────────────────────

    def _convert_string(self, raw: RawToken) -> SinglelineStringToken:
        """处理单行字符串：通过 json.loads 解析转义。

        无效转义（RawTokenizer 不校验，如 ``\\q`` / ``\\u``）→ 收集诊断，
        恢复为去引号的原始内容（不做转义处理），保证下游继续。
        """
        try:
            value = json.loads(raw.raw)
        except json.JSONDecodeError:
            self._errors.add(diag('tokenize.invalid_escape', {'raw': raw.raw}, raw.source))
            value = raw.raw[1:-1] if len(raw.raw) >= 2 else raw.raw
        return SinglelineStringToken(raw=raw, value=value)

    @staticmethod
    def _convert_multiline_string(raw: RawToken) -> MultilineStringToken:
        """处理多行字符串：提取 tags、修剪空白。"""
        content, tags = _process_multiline_string(raw.raw)
        return MultilineStringToken(raw=raw, value=content, tags=tags)

    def _convert_integer(self, raw: RawToken) -> IntegerToken:
        """解析整数字面量；失败收集诊断并回退 0（防御性：RawTokenizer 已校验）。"""
        try:
            value = int(raw.raw)
        except ValueError:
            self._errors.add(diag('tokenize.invalid_number', {'raw': raw.raw}, raw.source))
            value = 0
        return IntegerToken(raw=raw, value=value)

    def _convert_float(self, raw: RawToken) -> FloatToken:
        """解析浮点字面量（含 nan, +inf, -inf）。

        Decimal 拒绝的输入（如 ``1e`` 尾指数无数字）→ 收集诊断并回退 0。
        """
        s = raw.raw
        match s:
            case 'nan':
                value = decimal.Decimal('NaN')
            case '+inf':
                value = decimal.Decimal('Infinity')
            case '-inf':
                value = decimal.Decimal('-Infinity')
            case _:
                try:
                    value = decimal.Decimal(s)
                except decimal.InvalidOperation:
                    self._errors.add(diag('tokenize.invalid_float', {'raw': raw.raw}, raw.source))
                    value = decimal.Decimal(0)
        return FloatToken(raw=raw, value=value)

    @staticmethod
    def _convert_bool(raw: RawToken) -> BoolToken:
        """解析布尔字面量。"""
        return BoolToken(raw=raw, value=(raw.raw == 'true'))
