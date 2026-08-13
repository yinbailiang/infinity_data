"""词法分析阶段错误类型与收集器。"""

from dataclasses import dataclass
from typing import Literal

from infinity_data.infra.errors import ErrorCollector, InfinityDataError
from infinity_data.tokenizer.models.raw_tokens import RawTokenType, SourceInfo

# ═══════════════════════════════════════════════════════════
# 错误类型
# ═══════════════════════════════════════════════════════════


@dataclass
class TokenizeError(InfinityDataError[SourceInfo]):
    """词法分析阶段错误基类"""

    def _format_message(self) -> str:
        return '词法分析错误'


@dataclass
class UnknownCharError(TokenizeError):
    """未知字符错误。"""

    char: str

    def _format_message(self) -> str:
        return f'[{self.location}] 未知字符: {repr(self.char)}'


@dataclass
class UnterminatedStringError(TokenizeError):
    """字符串未闭合错误。"""

    str_type: Literal[RawTokenType.STRING, RawTokenType.MULTILINE_STRING]

    def _format_message(self) -> str:
        type_desc = '字符串' if self.str_type == RawTokenType.STRING else '多行字符串'
        return f'[{self.location}] {type_desc}未闭合'


@dataclass
class UnterminatedBracketError(TokenizeError):
    """括号未闭合错误。"""

    bracket_type: Literal[
        RawTokenType.LBRACE,
        RawTokenType.RBRACE,
        RawTokenType.LBRACKET,
        RawTokenType.RBRACKET,
        RawTokenType.LPAREN,
        RawTokenType.RPAREN,
        RawTokenType.LANGLE,
        RawTokenType.RANGLE,
    ]

    def _format_message(self) -> str:
        name = self.bracket_type.value
        return f'[{self.location}] 括号未闭合: {name}'


@dataclass
class InvalidNumberError(TokenizeError):
    """无效数字错误。"""

    raw: str

    def _format_message(self) -> str:
        return f'[{self.location}] 无效的数字字面量: {self.raw}'


@dataclass
class UnterminatedCommentError(TokenizeError):
    """注释未闭合错误。"""

    flag: str

    def _format_message(self) -> str:
        return f'[{self.location}] 多行注释未闭合，期望结束标记: {self.flag}'


class TokenizeErrorCollector(ErrorCollector[TokenizeError]):
    pass
