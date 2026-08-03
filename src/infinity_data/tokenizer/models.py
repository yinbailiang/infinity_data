"""InfinityData 词法分析 Token 模型。

基于 neo_desg.md 设计文档重新设计，支持：
- 多行注释 (#+ ... #-)
- Markdown 风格多行字符串
- 新字面量: nan, +inf, -inf, noexist
- 外部导入: !env, !file, !from
- $ 导入空间引用
- as 类型转换
- 逻辑约束关键字: not, any, one, all
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ═══════════════════════════════════════════════════════════
# Token 类型枚举
# ═══════════════════════════════════════════════════════════

class TokenType(Enum):
    """所有 token 类型。"""

    # ── 结构定界符 ─────────────────────────────────
    LBRACE = "{"
    RBRACE = "}"
    LBRACKET = "["
    RBRACKET = "]"
    LPAREN = "("
    RPAREN = ")"
    LANGLE = "<"
    RANGLE = ">"

    # ── 运算符 / 分隔符 ────────────────────────────
    EQUALS = "="
    COLON = ":"
    COMMA = ","
    TILDE = "~"
    EXCLAMATION = "!"
    QUESTION = "?"
    DOLLAR = "$"          # 导入命名空间引用前缀

    # ── 字面量 ─────────────────────────────────────
    STRING = "str"               # 双引号单行字符串
    MULTILINE_STRING = "mlstr"   # 反引号多行字符串
    INTEGER = "int"
    FLOAT = "float"

    # ── 特殊浮点字面量 ─────────────────────────────
    NAN = "nan"
    POS_INF = "+inf"
    NEG_INF = "-inf"

    # ── 布尔与存在性字面量 ─────────────────────────
    TRUE = "true"
    FALSE = "false"
    NULL = "null"
    NOEXIST = "noexist"          # 三态可空中的"不存在"

    # ── 标识符 / 关键字 ────────────────────────────
    IDENTIFIER = "identifier"

    # ── 导入关键字 ─────────────────────────────────
    FROM = "from"
    IMPORT = "import"
    ENV = "env"          # !env import ...
    FILE = "file"        # !file "path" as ...
    AS = "as"            # import ... as name / $NAME as type

    # ── 逻辑约束关键字 ─────────────────────────────
    NOT = "not"
    ANY = "any"
    ONE = "one"
    ALL = "all"

    # ── 换行 / EOF ─────────────────────────────────
    NEWLINE = "newline"
    EOF = "eof"


# ═══════════════════════════════════════════════════════════
# 关键字映射表
# ═══════════════════════════════════════════════════════════

KEYWORDS: dict[str, TokenType] = {
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "null": TokenType.NULL,
    "noexist": TokenType.NOEXIST,
    "nan": TokenType.NAN,
    "import": TokenType.IMPORT,
    "from": TokenType.FROM,
    "env": TokenType.ENV,
    "file": TokenType.FILE,
    "as": TokenType.AS,
    "not": TokenType.NOT,
    "any": TokenType.ANY,
    "one": TokenType.ONE,
    "all": TokenType.ALL,
}


# ═══════════════════════════════════════════════════════════
# 源码位置
# ═══════════════════════════════════════════════════════════

@dataclass
class SourceInfo:
    """源码位置信息。"""
    file: str
    line: int
    col: int
    start: int
    end: int


# ═══════════════════════════════════════════════════════════
# RawToken —— 词法分析第一阶段输出
# ═══════════════════════════════════════════════════════════

@dataclass
class RawToken:
    """第一阶段 token：保留原始文本，容错收集错误。"""
    type: TokenType
    raw: str
    source: SourceInfo


# ═══════════════════════════════════════════════════════════
# FinalToken 层次结构 —— 词法分析第二阶段输出
# ═══════════════════════════════════════════════════════════

@dataclass
class Token:
    """所有 FinalToken 的基类。"""
    source: SourceInfo
    type: TokenType = TokenType.EOF  # 子类应覆盖


# ── 结构定界符 ─────────────────────────────────────

@dataclass
class LbraceToken(Token):
    pass

@dataclass
class RbraceToken(Token):
    pass

@dataclass
class LbracketToken(Token):
    pass

@dataclass
class RbracketToken(Token):
    pass

@dataclass
class LparenToken(Token):
    pass

@dataclass
class RparenToken(Token):
    pass

@dataclass
class LangleToken(Token):
    pass

@dataclass
class RangleToken(Token):
    pass


# ── 运算符 / 分隔符 ─────────────────────────────────

@dataclass
class EqualsToken(Token):
    pass

@dataclass
class ColonToken(Token):
    pass

@dataclass
class CommaToken(Token):
    pass

@dataclass
class TildeToken(Token):
    pass

@dataclass
class ExclamationToken(Token):
    pass

@dataclass
class QuestionToken(Token):
    pass

@dataclass
class DollarToken(Token):
    """$ 导入命名空间引用前缀。"""


# ── 字面量 ─────────────────────────────────────────

@dataclass
class StringToken(Token):
    """双引号单行字符串。"""
    value: str = ""

@dataclass
class MultilineStringToken(Token):
    """反引号多行字符串。"""
    value: str = ""
    tag: str = ""  # 起始 `` 后可能跟的语言标注（如 text）

@dataclass
class IntegerToken(Token):
    """整数字面量。"""
    value: int = 0

@dataclass
class FloatToken(Token):
    """浮点数字面量。"""
    value: float = 0.0


# ── 特殊浮点字面量 ─────────────────────────────────

@dataclass
class NanToken(Token):
    """NaN。"""
    pass

@dataclass
class PosInfToken(Token):
    """+inf 正无穷。"""
    pass

@dataclass
class NegInfToken(Token):
    """-inf 负无穷。"""
    pass


# ── 布尔与存在性字面量 ─────────────────────────────

@dataclass
class TrueToken(Token):
    pass

@dataclass
class FalseToken(Token):
    pass

@dataclass
class NullToken(Token):
    pass

@dataclass
class NoexistToken(Token):
    """三态可空中的 noexist。"""
    pass


# ── 标识符 ─────────────────────────────────────────

@dataclass
class IdentifierToken(Token):
    """普通标识符 / 关键字。"""
    name: str = ""


# ── 导入相关 token ─────────────────────────────────

@dataclass
class FromToken(Token):
    pass

@dataclass
class ImportToken(Token):
    pass

@dataclass
class EnvToken(Token):
    """!env 关键字。"""
    pass

@dataclass
class FileToken(Token):
    """!file 关键字。"""
    pass

@dataclass
class AsToken(Token):
    """as 关键字。"""
    pass


# ── 逻辑约束 token ─────────────────────────────────

@dataclass
class NotToken(Token):
    pass

@dataclass
class AnyToken(Token):
    pass

@dataclass
class OneToken(Token):
    pass

@dataclass
class AllToken(Token):
    pass


# ── 换行 / EOF ─────────────────────────────────────

@dataclass
class NewlineToken(Token):
    pass

@dataclass
class EofToken(Token):
    pass


# ═══════════════════════════════════════════════════════════
# 词法错误
# ═══════════════════════════════════════════════════════════

@dataclass
class TokenizeError:
    """词法分析阶段错误。"""
    message: str
    source: SourceInfo


class TokenizeErrorCollector:
    """跨阶段错误收集器。"""

    def __init__(self) -> None:
        self._errors: list[TokenizeError] = []

    def add(self, message: str, source: SourceInfo) -> None:
        self._errors.append(TokenizeError(message=message, source=source))

    @property
    def errors(self) -> list[TokenizeError]:
        return list(self._errors)

    @property
    def has_errors(self) -> bool:
        return len(self._errors) > 0


# ═══════════════════════════════════════════════════════════
# TokenType → Token 类 映射表（供 FinalTokenizer 使用）
# ═══════════════════════════════════════════════════════════

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
    TokenType.DOLLAR: DollarToken,
    TokenType.NAN: NanToken,
    TokenType.POS_INF: PosInfToken,
    TokenType.NEG_INF: NegInfToken,
    TokenType.TRUE: TrueToken,
    TokenType.FALSE: FalseToken,
    TokenType.NULL: NullToken,
    TokenType.NOEXIST: NoexistToken,
    TokenType.FROM: FromToken,
    TokenType.IMPORT: ImportToken,
    TokenType.ENV: EnvToken,
    TokenType.FILE: FileToken,
    TokenType.AS: AsToken,
    TokenType.NOT: NotToken,
    TokenType.ANY: AnyToken,
    TokenType.ONE: OneToken,
    TokenType.ALL: AllToken,
    TokenType.NEWLINE: NewlineToken,
    TokenType.EOF: EofToken,
}


def make_final_token(token_type: TokenType, source: SourceInfo, **kwargs: object) -> Token:
    """根据 TokenType 创建对应的 FinalToken 实例。"""
    cls = _TOKEN_CLASS_MAP.get(token_type, Token)
    if cls is StringToken:
        return StringToken(type=token_type, source=source, value=str(kwargs.get("value", "")))
    if cls is MultilineStringToken:
        return MultilineStringToken(
            type=token_type,
            source=source,
            value=str(kwargs.get("value", "")),
            tag=str(kwargs.get("tag", "")),
        )
    if cls is IntegerToken:
        return IntegerToken(type=token_type, source=source, value=int(kwargs.get("value", 0)))
    if cls is FloatToken:
        return FloatToken(type=token_type, source=source, value=float(kwargs.get("value", 0.0)))
    if cls is IdentifierToken:
        return IdentifierToken(type=token_type, source=source, name=str(kwargs.get("name", "")))
    return cls(type=token_type, source=source)  # type: ignore[call-arg]
