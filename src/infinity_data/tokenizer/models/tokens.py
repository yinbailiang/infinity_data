import decimal
import json
from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class StarToken(Token):
    """*（单星：list 解包 / 可变参数位置捕获）"""

    pass


@dataclass
class DoubleStarToken(Token):
    """**（双星：dict 解包 / 可变参数命名捕获）"""

    pass


@dataclass
class EllipsisToken(Token):
    """...（三连点：模板展开轴 / 展开传播标记）"""

    pass


@dataclass
class CaretToken(Token):
    """^（调用级后缀：笛卡尔积展开，§2.8）"""

    pass


@dataclass
class VarImportToken(Token):
    """!var（本地 $ 空间注入：值表达式 + JSON path 投影）"""

    pass


# ── 字符串字面量 ───────────────────────────────────


@dataclass(init=False)
class StringToken(Token):
    """字符串基类（抽象：拒绝直接实例化，由单行/多行子类承载）"""

    value: str = ''

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError(
            'StringToken 是抽象字符串基类，不能直接实例化；请使用 SinglelineStringToken 或 MultilineStringToken'
        )

    def canonical(self) -> str:
        return json.dumps(self.value, ensure_ascii=False)


@dataclass
class SinglelineStringToken(StringToken):
    """双引号单行字符串（默认值仅用于错误恢复时的合成 token）"""

    def canonical(self) -> str:
        return json.dumps(self.value, ensure_ascii=False)


@dataclass
class MultilineStringToken(StringToken):
    """反引号多行字符串（默认值仅用于错误恢复时的合成 token）"""

    tags: list[str] = field(default_factory=lambda: [])

    def canonical(self) -> str:
        # 多行 → 标准单行字符串字面量（tags 不进内容）
        return json.dumps(self.value, ensure_ascii=False)


# ── 数字字面量 ─────────────────────────────────────


@dataclass
class IntegerToken(Token):
    """整数字面量（默认值仅用于错误恢复时的合成 token）"""

    value: int = 0

    def canonical(self) -> str:
        return str(self.value)


@dataclass
class FloatToken(Token):
    """浮点数字面量（默认值仅用于错误恢复时的合成 token）"""

    value: decimal.Decimal = field(default_factory=lambda: decimal.Decimal(0))

    def canonical(self) -> str:
        v = self.value
        if v.is_nan():
            return 'nan'
        if v.is_infinite():
            return '+inf' if v > 0 else '-inf'
        return str(v)


# ── 布尔字面量 ─────────────────────────────────────


@dataclass
class BoolToken(Token):
    """布尔字面量（默认值仅用于错误恢复时的合成 token）"""

    value: bool = False

    def canonical(self) -> str:
        return 'true' if self.value else 'false'


# ── 存在性字面量 ───────────────────────────────────


@dataclass
class NullToken(Token):
    """null"""

    def canonical(self) -> str:
        return 'null'


@dataclass
class NoexistToken(Token):
    """noexist"""

    def canonical(self) -> str:
        return 'noexist'


# ── 标识符 ─────────────────────────────────────────


@dataclass
class IdentifierToken(Token):
    """标识符"""

    name: str = ''


# ── 导入相关 token ─────────────────────────────────


@dataclass
class EnvImportToken(Token):
    """!env"""

    pass


@dataclass
class FileImportToken(Token):
    """!file"""

    pass


@dataclass
class FromImportToken(Token):
    """!from"""

    pass


# ── 换行 / EOF ─────────────────────────────────────


@dataclass
class NewlineToken(Token):
    pass


@dataclass
class EofToken(Token):
    pass
