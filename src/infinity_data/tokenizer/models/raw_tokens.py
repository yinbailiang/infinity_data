from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from infinity_data.infra.location import SourceInfo, SourceRange

__all__ = ['RawTokenType', 'RawToken', 'SourceInfo', 'SourceRange']


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
    STAR = '*'  # 单星：list 解包 / 可变参数位置捕获
    DOUBLE_STAR = '**'  # 双星：dict 解包 / 可变参数命名捕获
    ELLIPSIS = '...'  # 三连点：模板展开轴 / 展开传播标记
    CARET = '^'  # 调用级后缀：笛卡尔积展开（§2.8）

    # ── 字面量 ─────────────────────────────────────
    STRING = 'str'  # 双引号单行字符串
    PATH = 'path'  # p"..." 路径字面量（§1.5）
    MULTILINE_STRING = 'mlstr'  # 反引号多行字符串
    INTEGER = 'int'
    FLOAT = 'float'
    BOOL = 'bool'

    NULL = 'null'
    NOEXIST = 'noexist'

    # ── 标识符 / 关键字 ────────────────────────────
    IDENTIFIER = 'identifier'  # 裸标识符（[A-Za-z_][A-Za-z0-9_]*）
    STRING_IDENTIFIER = 'str_identifier'  # 单引号标识符（'a-b@c$d'）

    # ── Bang 组合关键字（! + 标识符，词法阶段识别，避免语法阶段二义）──
    BANG_KEYWORD = 'bang_keyword'  # raw='!env' / '!file' / '!from' / '!var' / '!assert'

    # ── 换行 / EOF ─────────────────────────────────
    NEWLINE = 'newline'
    EOF = 'eof'


@dataclass
class RawToken:
    type: RawTokenType
    raw: str
    source: SourceRange
