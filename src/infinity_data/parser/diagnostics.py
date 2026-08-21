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
    diagnostic_define(
        'parse.unrecognized_statement',
        '[{location}] 无法识别的顶层 token: {name}',
        en='[{location}] unrecognized top-level token: {name}',
    ),
    diagnostic_define(
        'parse.unrecognized_import', '[{location}] 无法识别的导入语句', en='[{location}] unrecognized import statement'
    ),
    diagnostic_define(
        'parse.unexpected_token',
        '[{location}] 期望 {expected}，实际为 {actual}',
        en='[{location}] expected {expected}, got {actual}',
    ),
    diagnostic_define(
        'parse.template_arg_order',
        '[{location}] 位置参数不能出现在命名参数之后',
        en='[{location}] positional arguments cannot follow named arguments',
    ),
    diagnostic_define('parse.empty_token_list', 'Token 列表为空，无法解析', en='empty token list, nothing to parse'),
    diagnostic_define(
        'parse.invalid_json_path', '[{location}] 无效的 JSON 路径{detail}', en='[{location}] invalid JSON path{detail}'
    ),
    diagnostic_define(
        'parse.unrecognized_value', '[{location}] 无法解析的值: {name}', en='[{location}] unrecognized value: {name}'
    ),
    diagnostic_define(
        'parse.missing_separator',
        '[{location}] 元素之间缺少分隔符（逗号或换行，空格不构成分隔）',
        en='[{location}] missing separator between elements (comma or newline; space is not a separator)',
    ),
    diagnostic_define(
        'parse.import_missing_comma',
        '[{location}] 导入项之间必须用逗号分隔（import 列表不接受换行/空格分隔）',
        en='[{location}] import items must be separated by commas (newlines/spaces are not allowed)',
    ),
    diagnostic_define(
        'parse.import_requires_newline',
        '[{location}] 导入语句必须以换行结尾（同一行逗号后不能再接其他语句）',
        en='[{location}] import statement must end with a newline (cannot be followed by more tokens on the same line)',
    ),
    diagnostic_define(
        'parse.value_field',
        '[{location}] 值位置出现字段定义 {name}（外层数组/对象未闭合）',
        en='[{location}] field definition {name} in value position (enclosing array/object unclosed)',
    ),
    diagnostic_define(
        'parse.field_requires_equals',
        '[{location}] 字段 {name} 省略等号仅限复合值与模板调用，字面量/引用须用 = 赋值',
        en='[{location}] field {name}: "=" required here (omit "=" only for dict/array/template call)',
    ),
    diagnostic_define(
        'parse.template_field_no_constraint',
        '[{location}] 模板字段 {field} 必须有类型标注（如 {field}: int）',
        en='[{location}] template field {field} requires a type annotation (e.g. {field}: int)',
    ),
    diagnostic_define(
        'parse.empty_type_annotation',
        '[{location}] 字段 {field} 的类型标注为空（{field}: 后缺少约束）',
        en='[{location}] field {field} has an empty type annotation (no constraint after {field}:)',
    ),
    diagnostic_define(
        'parse.invalid_cast',
        '[{location}] 未知的类型转换 {type}（合法: bool/int/float/str）',
        en='[{location}] unknown cast type {type} (valid: bool/int/float/str)',
    ),
    diagnostic_define(
        'parse.unrecognized_constraint',
        '[{location}] 无法解析的约束: {name}',
        en='[{location}] unrecognized constraint: {name}',
    ),
    diagnostic_define('parse.statement_error', '{path_prefix}{message}'),
    diagnostic_define(
        'parse.template_config_unknown',
        '[{location}] 未知的模板配置项: {key}（合法项: {valid}）',
        en='[{location}] unknown template config key: {key} (valid: {valid})',
    ),
    diagnostic_define(
        'parse.template_config_type',
        '[{location}] 模板配置 {key} 期望 {expected}，实际为 {actual}',
        en='[{location}] template config {key} expects {expected}, got {actual}',
    ),
    diagnostic_define(
        'parse.template_config_value',
        '[{location}] 模板配置 {key} 必须是字面量（不支持 $ 引用 / 模板调用）',
        en='[{location}] template config {key} must be a literal (no $ refs / template calls)',
    ),
    diagnostic_define(
        'parse.nesting_too_deep',
        '[{location}] 嵌套层级超过上限 {limit}，深层内容被跳过',
        en='[{location}] nesting depth exceeds limit {limit}; deeper content skipped',
    ),
)


def diag(code: str, params: dict[str, Any], source: SourceRange | None) -> Diagnostic:
    """构造语法阶段错误诊断（severity 恒为 ERROR）。"""
    return Diagnostic(Severity.ERROR, code, params, source)
