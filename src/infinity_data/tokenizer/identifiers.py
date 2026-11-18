"""标识符拼写规则：裸标识符判定与 textual 渲染。

- 词法层判定「单引号标识符能否去引号」（冗余引号 → 警告 + 发射裸标识符）
- 语法层 canonical 输出判定「名字是否必须带引号」

两处共用同一谓词，避免「词法接受裸写、canonical 却加引号」的漂移。
"""

from __future__ import annotations

import json

from infinity_data.tokenizer.models.raw_tokens import RawTokenType
from infinity_data.tokenizer.models.tokens import quote_identifier

__all__ = [
    'LITERAL_KEYWORDS',
    'RESERVED_LITERAL_NAMES',
    'decode_string_identifier',
    'is_ascii_digit',
    'is_ascii_letter',
    'is_bare_identifier',
    'is_ident_char',
    'is_ident_start',
    'quote_identifier',
    'render_identifier',
]

# 保留字面量：裸写时被词法层识别为字面量，因此不能作为裸标识符
LITERAL_KEYWORDS: dict[str, RawTokenType] = {
    'null': RawTokenType.NULL,
    'noexist': RawTokenType.NOEXIST,
    'true': RawTokenType.BOOL,
    'false': RawTokenType.BOOL,
    'nan': RawTokenType.FLOAT,
}

RESERVED_LITERAL_NAMES: frozenset[str] = frozenset(LITERAL_KEYWORDS)


def is_ascii_letter(ch: str) -> bool:
    """ASCII 字母（标识符/关键字只允许 ASCII，规范 [A-Za-z_]）。"""
    return 'a' <= ch <= 'z' or 'A' <= ch <= 'Z'


def is_ascii_digit(ch: str) -> bool:
    """ASCII 数字（数字字面量只允许 [0-9]）。"""
    return '0' <= ch <= '9'


def is_ident_start(ch: str) -> bool:
    """标识符起始字符：字母或下划线。"""
    return is_ascii_letter(ch) or ch == '_'


def is_ident_char(ch: str) -> bool:
    """标识符组成字符：字母/数字/下划线。"""
    return is_ascii_letter(ch) or is_ascii_digit(ch) or ch == '_'


def is_bare_identifier(name: str) -> bool:
    """名字能否以裸标识符书写（字符集合法且不撞保留字面量）。"""
    if not name or not is_ident_start(name[0]):
        return False
    if not all(is_ident_char(ch) for ch in name):
        return False
    return name not in RESERVED_LITERAL_NAMES


def decode_string_identifier(raw: str) -> tuple[str, bool]:
    """``'...'`` → (解码值, 是否合法)：转换为 JSON 字符串后交给 :func:`json.loads`。

    只需处理两处与 JSON 的差异，其余转义（``\\n`` / ``\\uXXXX`` / 代理对等）全部复用
    JSON 解码，避免自写转义表与 Unicode 合并逻辑：

    - ``\\'``：单引号语法必需，转换为裸 ``'``
    - 裸 ``"``：需转义为 ``\\"``，否则会被当作 JSON 字符串结束
    """
    inner = raw[1:-1] if len(raw) >= 2 else ''
    parts: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == '\\':
            nxt = inner[i + 1 : i + 2]
            if not nxt:
                return '', False
            parts.append("'" if nxt == "'" else ch + nxt)
            i += 2
            continue
        parts.append('\\"' if ch == '"' else ch)
        i += 1
    try:
        return json.loads('"' + ''.join(parts) + '"'), True
    except json.JSONDecodeError:
        return '', False


def render_identifier(name: str) -> str:
    """canonical 拼写：能裸写则裸写，否则带引号。"""
    return name if is_bare_identifier(name) else quote_identifier(name)
