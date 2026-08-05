from dataclasses import dataclass
from typing import Literal

from infinity_data.tokenizer.models.raw_tokens import RawTokenType, SourceInfo


@dataclass
class TokenizeError:
    """词法分析阶段错误。"""
    source: SourceInfo

@dataclass
class UnknownCharError(TokenizeError):
    """未知字符错误。"""
    char: str

@dataclass
class UnterminatedStringError(TokenizeError):
    """字符串未闭合错误。"""
    str_type: Literal[RawTokenType.STRING, RawTokenType.MULTILINE_STRING]

@dataclass
class UnterminatedBracketError(TokenizeError):
    """括号未闭合错误。"""
    bracket_type: Literal[
        RawTokenType.LBRACE, RawTokenType.RBRACE,
        RawTokenType.LBRACKET, RawTokenType.RBRACKET,
        RawTokenType.LPAREN, RawTokenType.RPAREN,
        RawTokenType.LANGLE, RawTokenType.RANGLE,
    ]

@dataclass
class InvalidNumberError(TokenizeError):
    """无效数字错误。"""
    raw: str

@dataclass
class UnterminatedCommentError(TokenizeError):
    """注释未闭合错误。"""
    flag: str

class TokenizeErrorCollector:
    """跨阶段错误收集器。"""

    def __init__(self) -> None:
        self._errors: list[TokenizeError] = []

    def add(self, error: TokenizeError) -> None:
        self._errors.append(error)

    @property
    def errors(self) -> list[TokenizeError]:
        return self._errors.copy()

    @property
    def has_errors(self) -> bool:
        return len(self._errors) > 0