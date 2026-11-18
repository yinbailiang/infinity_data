"""词法分析阶段诊断声明（``tokenize.*``）。

每个诊断 = 一个 ``@dataclass(frozen=True)`` 声明类：``code`` / ``severity`` /
``templates`` 为 ``ClassVar``，字段为类型化渲染参数。导入本模块即完成注册
（需要导入方先 ``import infinity_data.tokenizer.diagnostics``）。
"""

from dataclasses import dataclass
from typing import ClassVar, Mapping

from infinity_data.infra.diagnostics import DiagnosticDeclaration, Severity, registry

__all__ = [
    'TokenizeUnknownChar',
    'TokenizeUnterminatedString',
    'TokenizeUnterminatedMultilineString',
    'TokenizeUnterminatedBracket',
    'TokenizeMismatchedBracket',
    'TokenizeUnexpectedCloseBracket',
    'TokenizeInvalidNumber',
    'TokenizeInvalidEscape',
    'TokenizeInvalidPath',
    'TokenizeInvalidFloat',
    'TokenizeInvalidBang',
    'TokenizeInvalidEllipsis',
    'TokenizeBangCorrected',
    'TokenizeSignedNan',
    'TokenizeUnterminatedComment',
    'TokenizeBom',
    'TokenizeUnterminatedIdentifier',
    'TokenizeEmptyIdentifier',
    'TokenizeRedundantIdentifierQuotes',
]


@registry.register
@dataclass(frozen=True)
class TokenizeUnknownChar(DiagnosticDeclaration):
    """未知字符。"""

    code: ClassVar[str] = 'tokenize.unknown_char'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}未知字符: {char!r}',
        'en-US': '{location_prefix}unknown character: {char!r}',
    }
    char: str


@registry.register
@dataclass(frozen=True)
class TokenizeUnterminatedString(DiagnosticDeclaration):
    """单行字符串未闭合。"""

    code: ClassVar[str] = 'tokenize.unterminated_string'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}字符串未闭合',
        'en-US': '{location_prefix}unterminated string literal',
    }


@registry.register
@dataclass(frozen=True)
class TokenizeUnterminatedMultilineString(DiagnosticDeclaration):
    """多行字符串未闭合。"""

    code: ClassVar[str] = 'tokenize.unterminated_multiline_string'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}多行字符串未闭合，期望结束标记: {flag}',
        'en-US': '{location_prefix}unterminated multiline string literal, expected closing: {flag}',
    }
    flag: str


@registry.register
@dataclass(frozen=True)
class TokenizeUnterminatedBracket(DiagnosticDeclaration):
    """括号未闭合。"""

    code: ClassVar[str] = 'tokenize.unterminated_bracket'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}括号未闭合: {bracket}',
        'en-US': '{location_prefix}unclosed bracket: {bracket}',
    }
    bracket: str


@registry.register
@dataclass(frozen=True)
class TokenizeMismatchedBracket(DiagnosticDeclaration):
    """括号不匹配。"""

    code: ClassVar[str] = 'tokenize.mismatched_bracket'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}括号不匹配: {open} 与 {close} 不配对',
        'en-US': '{location_prefix}mismatched brackets: {open} and {close} do not pair',
    }
    open: str
    close: str


@registry.register
@dataclass(frozen=True)
class TokenizeUnexpectedCloseBracket(DiagnosticDeclaration):
    """多余的闭合括号。"""

    code: ClassVar[str] = 'tokenize.unexpected_close_bracket'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}多余的闭合括号: {bracket}',
        'en-US': '{location_prefix}unexpected closing bracket: {bracket}',
    }
    bracket: str


@registry.register
@dataclass(frozen=True)
class TokenizeInvalidNumber(DiagnosticDeclaration):
    """无效数字字面量。"""

    code: ClassVar[str] = 'tokenize.invalid_number'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}无效的数字字面量: {raw!r}',
        'en-US': '{location_prefix}invalid number literal: {raw!r}',
    }
    raw: str


@registry.register
@dataclass(frozen=True)
class TokenizeInvalidEscape(DiagnosticDeclaration):
    """无效转义序列。"""

    code: ClassVar[str] = 'tokenize.invalid_escape'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}无效的转义序列: {raw!r}',
        'en-US': '{location_prefix}invalid escape sequence: {raw!r}',
    }
    raw: str


@registry.register
@dataclass(frozen=True)
class TokenizeInvalidPath(DiagnosticDeclaration):
    """无效路径字面量。"""

    code: ClassVar[str] = 'tokenize.invalid_path'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}无效的路径字面量（无法构造路径）: {raw!r}',
        'en-US': '{location_prefix}invalid path literal: {raw!r}',
    }
    raw: str


@registry.register
@dataclass(frozen=True)
class TokenizeInvalidFloat(DiagnosticDeclaration):
    """无效浮点字面量。"""

    code: ClassVar[str] = 'tokenize.invalid_float'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}无效的浮点字面量: {raw!r}',
        'en-US': '{location_prefix}invalid float literal: {raw!r}',
    }
    raw: str


@registry.register
@dataclass(frozen=True)
class TokenizeInvalidBang(DiagnosticDeclaration):
    """``!`` 后不是合法导入关键字。"""

    code: ClassVar[str] = 'tokenize.invalid_bang'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}! 后期望 env/file/from/var，实际为 {actual}',
        'en-US': "{location_prefix}expected env/file/from/var after '!', got {actual}",
    }
    actual: str


@registry.register
@dataclass(frozen=True)
class TokenizeInvalidEllipsis(DiagnosticDeclaration):
    """非法点串。"""

    code: ClassVar[str] = 'tokenize.invalid_ellipsis'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}非法点串（{count} 个点）：只有单点 . 与三连点 ... 合法',
        'en-US': '{location_prefix}invalid dot run of {count}: only . (1) and ... (3) are valid',
    }
    count: int


@registry.register
@dataclass(frozen=True)
class TokenizeBangCorrected(DiagnosticDeclaration):
    """``!`` 后关键字拼写纠正。"""

    code: ClassVar[str] = 'tokenize.bang_corrected'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}! 后 {actual} 疑似 {suggestion} 的笔误，已纠正为 !{suggestion}',
        'en-US': '{location_prefix}{actual} after ! looks like a typo for {suggestion}; corrected to !{suggestion}',
    }
    actual: str
    suggestion: str


@registry.register
@dataclass(frozen=True)
class TokenizeSignedNan(DiagnosticDeclaration):
    """带符号 NaN 归一化。"""

    code: ClassVar[str] = 'tokenize.signed_nan'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}带符号 NaN（{raw}），已归一化为 nan',
        'en-US': '{location_prefix}signed NaN ({raw}) normalized to nan',
    }
    raw: str


@registry.register
@dataclass(frozen=True)
class TokenizeUnterminatedComment(DiagnosticDeclaration):
    """多行注释未闭合。"""

    code: ClassVar[str] = 'tokenize.unterminated_comment'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}多行注释未闭合，期望结束标记: {flag}',
        'en-US': '{location_prefix}unterminated block comment, expected closing: {flag}',
    }
    flag: str


@registry.register
@dataclass(frozen=True)
class TokenizeBom(DiagnosticDeclaration):
    """文件包含 BOM。"""

    code: ClassVar[str] = 'tokenize.bom'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}文件包含 BOM，规范要求 UTF-8 NO BOM 编码',
        'en-US': '{location_prefix}file contains a BOM; UTF-8 NO BOM is required',
    }


@registry.register
@dataclass(frozen=True)
class TokenizeUnterminatedIdentifier(DiagnosticDeclaration):
    """单引号标识符未闭合。"""

    code: ClassVar[str] = 'tokenize.unterminated_identifier'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}字符串标识符未闭合（缺少结束单引号）',
        'en-US': '{location_prefix}unterminated string identifier (missing closing single quote)',
    }


@registry.register
@dataclass(frozen=True)
class TokenizeEmptyIdentifier(DiagnosticDeclaration):
    """空字符串标识符。"""

    code: ClassVar[str] = 'tokenize.empty_identifier'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}字符串标识符不能为空',
        'en-US': '{location_prefix}string identifier must not be empty',
    }


@registry.register
@dataclass(frozen=True)
class TokenizeRedundantIdentifierQuotes(DiagnosticDeclaration):
    """单引号标识符可裸写（冗余引号）。"""

    code: ClassVar[str] = 'tokenize.redundant_identifier_quotes'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}标识符 {name!r} 可以裸写，视为裸写',
        'en-US': '{location_prefix}identifier {name!r} can be written bare; treated as bare',
    }
    name: str
