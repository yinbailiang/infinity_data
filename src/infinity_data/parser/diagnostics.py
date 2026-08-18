"""语法分析阶段诊断构造器与诊断定义。

语法错误统一为 :class:`Diagnostic`（纯数据，从不抛异常）；
:func:`diag` 便捷构造语法错误诊断，收集使用 :class:`DiagnosticCollector`。
诊断定义（``parse.*``）导入时注册进全局注册表（:func:`register`）。
"""

from typing import Any

from infinity_data.infra.diagnostics import Diagnostic, Severity, diagnostic_define, register_diagnostic_define
from infinity_data.infra.location import SourceRange

__all__ = ['diag']

register_diagnostic_define(
    diagnostic_define('parse.unrecognized_statement', '[{location}] 无法识别的顶层 token: {name}', en='[{location}] unrecognized top-level token: {name}'),
    diagnostic_define('parse.unrecognized_import', '[{location}] 无法识别的导入语句', en='[{location}] unrecognized import statement'),
    diagnostic_define('parse.unexpected_token', '[{location}] 期望 {expected}，实际为 {actual}', en='[{location}] expected {expected}, got {actual}'),
    diagnostic_define(
        'parse.template_arg_order',
        '[{location}] 位置参数不能出现在命名参数之后',
        en='[{location}] positional arguments cannot follow named arguments',
    ),
    diagnostic_define('parse.empty_token_list', 'Token 列表为空，无法解析', en='empty token list, nothing to parse'),
    diagnostic_define('parse.invalid_json_path', '[{location}] 无效的 JSON 路径{detail}', en='[{location}] invalid JSON path{detail}'),
    diagnostic_define('parse.unrecognized_value', '[{location}] 无法解析的值: {name}', en='[{location}] unrecognized value: {name}'),
    diagnostic_define('parse.unrecognized_constraint', '[{location}] 无法解析的约束: {name}', en='[{location}] unrecognized constraint: {name}'),
    diagnostic_define('parse.statement_error', '{path_prefix}{message}'),
)


def diag(code: str, params: dict[str, Any], source: SourceRange | None) -> Diagnostic:
    """构造语法阶段错误诊断（severity 恒为 ERROR）。"""
    return Diagnostic(Severity.ERROR, code, params, source)
