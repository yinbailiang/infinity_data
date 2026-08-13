from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RawTokenType(Enum):
    """所有 token 类型。"""

    # ── 结构定界符 ─────────────────────────────────
    LBRACE = '{'
    RBRACE = '}'
    LBRACKET = '['
    RBRACKET = ']'
    LPAREN = '('
    RPAREN = ')'
    LANGLE = '<'
    RANGLE = '>'

    # ── 运算符 / 分隔符 ────────────────────────────
    EQUALS = '='
    COLON = ':'
    COMMA = ','
    TILDE = '~'
    EXCLAMATION = '!'
    QUESTION = '?'
    DOLLAR = '$'  # 导入命名空间引用前缀
    DOT = '.'  # 导入命名空间引用分隔符

    # ── 字面量 ─────────────────────────────────────
    STRING = 'str'  # 双引号单行字符串
    MULTILINE_STRING = 'mlstr'  # 反引号多行字符串
    INTEGER = 'int'
    FLOAT = 'float'
    BOOL = 'bool'

    NULL = 'null'
    NOEXIST = 'noexist'

    # ── 标识符 / 关键字 ────────────────────────────
    IDENTIFIER = 'identifier'

    # ── 导入关键字 ─────────────────────────────────
    FROM = 'from'  # !from import ...
    IMPORT = 'import'  # ... import ...
    ENV = 'env'  # !env import ...
    FILE = 'file'  # !file "path" as ...
    AS = 'as'  # import ... as name / $NAME as type

    # ── 换行 / EOF ─────────────────────────────────
    NEWLINE = 'newline'
    EOF = 'eof'


@dataclass
class SourceInfo:
    """源码位置信息。"""

    file_path: str
    line: int
    col: int
    index: int


@dataclass
class SourceRange:
    """源码位置范围。"""

    start: SourceInfo
    end: SourceInfo


@dataclass
class RawToken:
    type: RawTokenType
    raw: str
    source: SourceRange
