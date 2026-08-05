import decimal
from dataclasses import dataclass

from .raw_tokens import RawToken


@dataclass
class Token:
    raw: RawToken


@dataclass
class LbraceToken(Token):
    """{"""
    pass

@dataclass
class RbraceToken(Token):
    """}"""
    pass

@dataclass
class LbracketToken(Token):
    """["""
    pass

@dataclass
class RbracketToken(Token):
    """]"""
    pass

@dataclass
class LparenToken(Token):
    """("""
    pass

@dataclass
class RparenToken(Token):
    """)"""
    pass

@dataclass
class LangleToken(Token):
    """<"""
    pass

@dataclass
class RangleToken(Token):
    """>"""
    pass


# ── 运算符 / 分隔符 ─────────────────────────────────

@dataclass
class EqualsToken(Token):
    """="""
    pass

@dataclass
class ColonToken(Token):
    """:"""
    pass

@dataclass
class CommaToken(Token):
    ""","""
    pass

@dataclass
class TildeToken(Token):
    """~"""
    pass

@dataclass
class ExclamationToken(Token):
    """!"""
    pass

@dataclass
class QuestionToken(Token):
    """?"""
    pass

@dataclass
class DollarToken(Token):
    """$"""
    pass

@dataclass
class DotToken(Token):
    """."""
    pass


# ── 字符串字面量 ───────────────────────────────────

@dataclass
class StringToken(Token):
    """字符串"""
    value: str

@dataclass
class SinglelineStringToken(StringToken):
    """双引号单行字符串"""
    pass

@dataclass
class MultilineStringToken(StringToken):
    """反引号多行字符串"""
    tags: list[str]


# ── 数字字面量 ─────────────────────────────────────

@dataclass
class IntegerToken(Token):
    """整数字面量。"""
    value: int

@dataclass
class FloatToken(Token):
    """浮点数字面量。"""
    value: decimal.Decimal


# ── 布尔字面量 ─────────────────────────────────────

@dataclass
class BoolToken(Token):
    """布尔字面量。"""
    value: bool


# ── 存在性字面量 ───────────────────────────────────

@dataclass
class NullToken(Token):
    """null"""
    pass

@dataclass
class NoexistToken(Token):
    """noexist"""
    pass


# ── 标识符 ─────────────────────────────────────────

@dataclass
class IdentifierToken(Token):
    """标识符"""
    name: str = ""


# ── 导入相关 token ─────────────────────────────────

@dataclass
class FromToken(Token):
    """from"""
    pass

@dataclass
class ImportToken(Token):
    """import"""
    pass

@dataclass
class EnvToken(Token):
    """env"""
    pass

@dataclass
class FileToken(Token):
    """file"""
    pass

@dataclass
class AsToken(Token):
    """as"""
    pass


# ── 换行 / EOF ─────────────────────────────────────

@dataclass
class NewlineToken(Token):
    pass

@dataclass
class EofToken(Token):
    pass
