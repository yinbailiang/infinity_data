from dataclasses import dataclass
from enum import Enum

class TokenType(Enum):
    # 结构定界符
    LBRACE = "{"
    RBRACE = "}"
    LBRACKET = "["
    RBRACKET = "]"
    LPAREN = "("
    RPAREN = ")"
    LANGLE = "<"
    RANGLE = ">"

    # 运算符 / 分隔符
    EQUALS = "="
    COLON = ":"
    COMMA = ","
    AT = "@"
    EXCLAMATION = "!"
    QUESTION = "?"

    # 字面量
    STRING = "str"
    INTEGER = "int"
    FLOAT = "float"

    # 布尔与特殊字面量
    TRUE = "true"
    FALSE = "false"
    NULL = "null"
    EXIST = "exist"

    IDENTIFIER = "identifier"

    FROM = "from"
    IMPORT= "import"

    # 换行（作为分隔符，与逗号近乎等价）
    NEWLINE = "newline"

    EOF = "eof"


@dataclass
class SourceInfo:
    file: str
    line: int
    col: int
    start: int
    end: int


@dataclass
class RawToken:
    type: TokenType
    raw: str
    source: SourceInfo

@dataclass
class Token:
    source: SourceInfo
    type: TokenType

@dataclass
class LbraceToken(Token):
    type: TokenType = TokenType.LBRACE

@dataclass
class RbraceToken(Token):
    type: TokenType = TokenType.RBRACE

@dataclass
class LbracketToken(Token):
    type: TokenType = TokenType.LBRACKET

@dataclass
class RbracketToken(Token):
    type: TokenType = TokenType.RBRACKET

@dataclass
class LparenToken(Token):
    type: TokenType = TokenType.LPAREN

@dataclass
class RparenToken(Token):
    type: TokenType = TokenType.RPAREN

@dataclass
class LangleToken(Token):
    type: TokenType = TokenType.LANGLE

@dataclass
class RangleToken(Token):
    type: TokenType = TokenType.RANGLE

@dataclass
class EqualsToken(Token):
    type: TokenType = TokenType.EQUALS

@dataclass
class ColonToken(Token):
    type: TokenType = TokenType.COLON

@dataclass
class CommaToken(Token):
    type: TokenType = TokenType.COMMA

@dataclass
class AtToken(Token):
    type: TokenType = TokenType.AT

@dataclass
class ExclamationToken(Token):
    type: TokenType = TokenType.EXCLAMATION

@dataclass
class QuestionToken(Token):
    type: TokenType = TokenType.QUESTION

@dataclass
class StringToken(Token):
    type: TokenType = TokenType.STRING
    value: str = ""

@dataclass
class IntegerToken(Token):
    type: TokenType = TokenType.INTEGER
    value: int = 0

@dataclass
class FloatToken(Token):
    type: TokenType = TokenType.FLOAT
    value: float = 0.0

@dataclass
class TrueToken(Token):
    type: TokenType = TokenType.TRUE

@dataclass
class FalseToken(Token):
    type: TokenType = TokenType.FALSE

@dataclass
class NullToken(Token):
    type: TokenType = TokenType.NULL

@dataclass
class ExistToken(Token):
    type: TokenType = TokenType.EXIST

@dataclass
class IdentifierToken(Token):
    type: TokenType = TokenType.IDENTIFIER
    name: str = ""

@dataclass
class FromToken(Token):
    type: TokenType = TokenType.FROM

@dataclass
class ImportToken(Token):
    type: TokenType = TokenType.IMPORT

@dataclass
class NewlineToken(Token):
    type: TokenType = TokenType.NEWLINE

@dataclass
class EofToken(Token):
    type: TokenType = TokenType.EOF