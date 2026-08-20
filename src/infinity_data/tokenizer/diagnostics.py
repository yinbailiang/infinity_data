"""词法分析阶段诊断构造器与诊断定义。

词法错误统一为 :class:`Diagnostic`（纯数据，从不抛异常）；
:func:`diag` 便捷构造词法错误诊断，收集使用 :class:`DiagnosticCollector`。
诊断定义（``tokenize.*``）导入时注册进全局注册表（:func:`register`）。
"""

from typing import Any

from infinity_data.infra.diagnostics import Diagnostic, Severity, diagnostic_define, register_diagnostic_define
from infinity_data.infra.location import SourceRange

__all__ = ['diag']

register_diagnostic_define(
    diagnostic_define(
        'tokenize.unknown_char', '[{location}] 未知字符: {char!r}', en='[{location}] unknown character: {char!r}'
    ),
    diagnostic_define(
        'tokenize.unterminated_string', '[{location}] {str_type}未闭合', en='[{location}] unterminated {str_type}'
    ),
    diagnostic_define(
        'tokenize.unterminated_bracket',
        '[{location}] 括号未闭合: {bracket}',
        en='[{location}] unclosed bracket: {bracket}',
    ),
    diagnostic_define(
        'tokenize.invalid_number',
        '[{location}] 无效的数字字面量: {raw!r}',
        en='[{location}] invalid number literal: {raw!r}',
    ),
    diagnostic_define(
        'tokenize.invalid_escape',
        '[{location}] 无效的转义序列: {raw!r}',
        en='[{location}] invalid escape sequence: {raw!r}',
    ),
    diagnostic_define(
        'tokenize.invalid_float',
        '[{location}] 无效的浮点字面量: {raw!r}',
        en='[{location}] invalid float literal: {raw!r}',
    ),
    diagnostic_define(
        'tokenize.invalid_bang',
        '[{location}] ! 后期望 env/file/from，实际为 {actual}',
        en="[{location}] expected env/file/from after '!', got {actual}",
    ),
    diagnostic_define(
        'tokenize.unterminated_comment',
        '[{location}] 多行注释未闭合，期望结束标记: {flag}',
        en='[{location}] unterminated block comment, expected closing: {flag}',
    ),
    diagnostic_define(
        'tokenize.bom',
        '[{location}] 文件包含 BOM，规范要求 UTF-8 NO BOM 编码',
        en='[{location}] file contains a BOM; UTF-8 NO BOM is required',
    ),
)


def diag(code: str, params: dict[str, Any], source: SourceRange | None) -> Diagnostic:
    """构造词法阶段错误诊断（severity 恒为 ERROR）。"""
    return Diagnostic(Severity.ERROR, code, params, source)
