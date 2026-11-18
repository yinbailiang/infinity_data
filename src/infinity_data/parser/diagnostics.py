"""语法分析阶段诊断声明（``parse.*``）。

每个诊断 = 一个 ``@dataclass(frozen=True)`` 声明类：``code`` / ``severity`` /
``templates`` 为 ``ClassVar``，字段为类型化渲染参数。导入本模块即完成注册。
"""

from dataclasses import dataclass
from typing import ClassVar, Mapping

from infinity_data.infra.diagnostics import DiagnosticDeclaration, Severity, registry

__all__ = [
    'ParseUnrecognizedStatement',
    'ParseUnrecognizedImport',
    'ParseUnexpectedToken',
    'ParseExpectedKeyword',
    'ParseAssertMissingConstraint',
    'ParseExpandOutsideCall',
    'ParseExpandSuffixOrder',
    'ParsePostfixOrder',
    'ParseTemplateArgOrder',
    'ParseEmptyTokenList',
    'ParseJsonPathMustStartDot',
    'ParseJsonPathMissingSegment',
    'ParseJsonPathMissingAliasOrSegment',
    'ParseJsonPathMissingCloseBracket',
    'ParseJsonPathIndexExpected',
    'ParseUnrecognizedValue',
    'ParseStringIdentifierMisplaced',
    'ParseMissingSeparator',
    'ParseImportMissingComma',
    'ParseImportRequiresNewline',
    'ParseImportPathRequired',
    'ParseValueField',
    'ParseFieldRequiresEquals',
    'ParseTemplateFieldNoConstraint',
    'ParseEmptyTypeAnnotation',
    'ParseInvalidCast',
    'ParseUnrecognizedConstraint',
    'ParseTemplateConfigUnknown',
    'ParseTemplateConfigType',
    'ParseTemplateConfigValue',
    'ParseNestingTooDeep',
    'TemplateDupArgument',
]


@registry.register
@dataclass(frozen=True)
class ParseUnrecognizedStatement(DiagnosticDeclaration):
    """无法识别的顶层 token。"""

    code: ClassVar[str] = 'parse.unrecognized_statement'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}无法识别的顶层 token: {name}',
        'en-US': '{location_prefix}unrecognized top-level token: {name}',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class ParseUnrecognizedImport(DiagnosticDeclaration):
    """无法识别的导入语句。"""

    code: ClassVar[str] = 'parse.unrecognized_import'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}无法识别的导入语句',
        'en-US': '{location_prefix}unrecognized import statement',
    }


@registry.register
@dataclass(frozen=True)
class ParseUnexpectedToken(DiagnosticDeclaration):
    """期望 token 与实际不符。"""

    code: ClassVar[str] = 'parse.unexpected_token'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}期望 {expected}，实际为 {actual}',
        'en-US': '{location_prefix}expected {expected}, got {actual}',
    }
    expected: str
    actual: str


@registry.register
@dataclass(frozen=True)
class ParseExpectedKeyword(DiagnosticDeclaration):
    """期望关键字但实际 token 不符。"""

    code: ClassVar[str] = 'parse.expected_keyword'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}期望关键字 {keyword!r}，实际为 {actual}',
        'en-US': '{location_prefix}expected keyword {keyword!r}, got {actual}',
    }
    keyword: str
    actual: str


@registry.register
@dataclass(frozen=True)
class ParseAssertMissingConstraint(DiagnosticDeclaration):
    """!assert 的 is 后缺少约束。"""

    code: ClassVar[str] = 'parse.assert_missing_constraint'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}!assert 的 is 后缺少约束',
        'en-US': '{location_prefix}!assert is missing a constraint after is',
    }


@registry.register
@dataclass(frozen=True)
class ParseExpandOutsideCall(DiagnosticDeclaration):
    """``...`` 出现在非模板调用参数上下文。"""

    code: ClassVar[str] = 'parse.expand_outside_call'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}... 只能在模板调用参数上下文使用（展开轴 / 展开传播，§2.8）',
        'en-US': '{location_prefix}... is only valid in template call argument context (expand axis / propagate)',
    }


@registry.register
@dataclass(frozen=True)
class ParseExpandSuffixOrder(DiagnosticDeclaration):
    """调用级后缀顺序错误。"""

    code: ClassVar[str] = 'parse.expand_suffix_order'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}... 后不能再跟 ^（调用级后缀顺序固定：^ 笛卡尔积 → ... 传播，§2.8）',
        'en-US': '{location_prefix}^ cannot follow ... (call-level suffix order: ^ cartesian → ... propagate)',
    }


@registry.register
@dataclass(frozen=True)
class ParsePostfixOrder(DiagnosticDeclaration):
    """``!?`` 后缀顺序建议。"""

    code: ClassVar[str] = 'parse.postfix_order'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}约束后缀 `!?` 与 `?!` 等价，推荐写作 `?!`（先可空 `?`、后可缺失 `!`）',
        'en-US': '{location_prefix}constraint suffix `!?` equals `?!`; prefer `?!` (nullable then absent)',
    }


@registry.register
@dataclass(frozen=True)
class ParseTemplateArgOrder(DiagnosticDeclaration):
    """位置参数出现在命名参数之后。"""

    code: ClassVar[str] = 'parse.template_arg_order'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}位置参数不能出现在命名参数之后',
        'en-US': '{location_prefix}positional arguments cannot follow named arguments',
    }


@registry.register
@dataclass(frozen=True)
class ParseEmptyTokenList(DiagnosticDeclaration):
    """Token 列表为空。"""

    code: ClassVar[str] = 'parse.empty_token_list'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': 'Token 列表为空，无法解析',
        'en-US': 'empty token list, nothing to parse',
    }


@registry.register
@dataclass(frozen=True)
class ParseJsonPathMustStartDot(DiagnosticDeclaration):
    """JSON 路径未以 . 起始。"""

    code: ClassVar[str] = 'parse.json_path_must_start_dot'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}JSON 路径必须以 . 起始',
        'en-US': '{location_prefix}JSON path must start with .',
    }


@registry.register
@dataclass(frozen=True)
class ParseJsonPathMissingSegment(DiagnosticDeclaration):
    """. 后缺少段名。"""

    code: ClassVar[str] = 'parse.json_path_missing_segment'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}. 后缺少段名',
        'en-US': '{location_prefix}missing path segment after .',
    }


@registry.register
@dataclass(frozen=True)
class ParseJsonPathMissingAliasOrSegment(DiagnosticDeclaration):
    """. 后需要段名或 as 别名。"""

    code: ClassVar[str] = 'parse.json_path_missing_alias_or_segment'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}. 后需要段名或 as 别名',
        'en-US': '{location_prefix}expected a path segment or as alias after .',
    }


@registry.register
@dataclass(frozen=True)
class ParseJsonPathMissingCloseBracket(DiagnosticDeclaration):
    """[ 下标后缺少 ]。"""

    code: ClassVar[str] = 'parse.json_path_missing_close_bracket'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}[ 下标后缺少 ]',
        'en-US': '{location_prefix}missing ] after index',
    }


@registry.register
@dataclass(frozen=True)
class ParseJsonPathIndexExpected(DiagnosticDeclaration):
    """[ 后须为整数下标。"""

    code: ClassVar[str] = 'parse.json_path_index_expected'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}[ 后须为整数下标',
        'en-US': '{location_prefix}expected an integer index after [',
    }


@registry.register
@dataclass(frozen=True)
class ParseUnrecognizedValue(DiagnosticDeclaration):
    """无法解析的值。"""

    code: ClassVar[str] = 'parse.unrecognized_value'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}无法解析的值: {name}',
        'en-US': '{location_prefix}unrecognized value: {name}',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class ParseMissingSeparator(DiagnosticDeclaration):
    """元素之间缺少分隔符。"""

    code: ClassVar[str] = 'parse.missing_separator'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}元素之间缺少分隔符（逗号或换行，空格不构成分隔）',
        'en-US': '{location_prefix}missing separator between elements (comma or newline; space is not a separator)',
    }


@registry.register
@dataclass(frozen=True)
class ParseImportMissingComma(DiagnosticDeclaration):
    """导入项缺少逗号。"""

    code: ClassVar[str] = 'parse.import_missing_comma'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}导入项之间必须用逗号分隔（import 列表不接受换行/空格分隔）',
        'en-US': '{location_prefix}import items must be separated by commas (newlines/spaces are not allowed)',
    }


@registry.register
@dataclass(frozen=True)
class ParseImportRequiresNewline(DiagnosticDeclaration):
    """导入语句未换行结尾。"""

    code: ClassVar[str] = 'parse.import_requires_newline'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}导入语句必须以换行结尾（同一行逗号后不能再接其他语句）',
        'en-US': '{location_prefix}import statement must end with a newline (cannot be followed by more tokens on the same line)',
    }
    actual: str


@registry.register
@dataclass(frozen=True)
class ParseImportPathRequired(DiagnosticDeclaration):
    """导入路径必须是路径字面量。"""

    code: ClassVar[str] = 'parse.import_path_required'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}导入路径必须用 p"..." 路径字面量（§1.5 / §3.2），已按字符串容错取用',
        'en-US': '{location_prefix}import path must use a p"..." path literal (§1.5 / §3.2); recovered as string',
    }


@registry.register
@dataclass(frozen=True)
class ParseValueField(DiagnosticDeclaration):
    """值位置出现字段定义。"""

    code: ClassVar[str] = 'parse.value_field'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}值位置出现字段定义 {name}（外层数组/对象未闭合）',
        'en-US': '{location_prefix}field definition {name} in value position (enclosing array/object unclosed)',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class ParseFieldRequiresEquals(DiagnosticDeclaration):
    """字面量/引用字段省略等号。"""

    code: ClassVar[str] = 'parse.field_requires_equals'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}字段 {name} 省略等号仅限复合值与模板调用，字面量/引用须用 = 赋值',
        'en-US': '{location_prefix}field {name}: "=" required here (omit "=" only for dict/array/template call)',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class ParseTemplateFieldNoConstraint(DiagnosticDeclaration):
    """模板字段缺少类型标注。"""

    code: ClassVar[str] = 'parse.template_field_no_constraint'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}模板字段 {field} 必须有类型标注（如 {field}: int）',
        'en-US': '{location_prefix}template field {field} requires a type annotation (e.g. {field}: int)',
    }
    field: str


@registry.register
@dataclass(frozen=True)
class ParseEmptyTypeAnnotation(DiagnosticDeclaration):
    """字段类型标注为空。"""

    code: ClassVar[str] = 'parse.empty_type_annotation'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}字段 {field} 的类型标注为空（{field}: 后缺少约束）',
        'en-US': '{location_prefix}field {field} has an empty type annotation (no constraint after {field}:)',
    }
    field: str


@registry.register
@dataclass(frozen=True)
class ParseInvalidCast(DiagnosticDeclaration):
    """未知类型转换。"""

    code: ClassVar[str] = 'parse.invalid_cast'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}未知的类型转换 {type}（合法: bool/int/float/str）',
        'en-US': '{location_prefix}unknown cast type {type} (valid: bool/int/float/str)',
    }
    type: str


@registry.register
@dataclass(frozen=True)
class ParseUnrecognizedConstraint(DiagnosticDeclaration):
    """无法解析的约束。"""

    code: ClassVar[str] = 'parse.unrecognized_constraint'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}无法解析的约束: {name}',
        'en-US': '{location_prefix}unrecognized constraint: {name}',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class ParseTemplateConfigUnknown(DiagnosticDeclaration):
    """未知模板配置项。"""

    code: ClassVar[str] = 'parse.template_config_unknown'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}未知的模板配置项: {key}（合法项: {valid}）',
        'en-US': '{location_prefix}unknown template config key: {key} (valid: {valid})',
    }
    key: str
    valid: str


@registry.register
@dataclass(frozen=True)
class ParseTemplateConfigType(DiagnosticDeclaration):
    """模板配置项类型错误。"""

    code: ClassVar[str] = 'parse.template_config_type'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}模板配置 {key} 期望 {expected}，实际为 {actual}',
        'en-US': '{location_prefix}template config {key} expects {expected}, got {actual}',
    }
    key: str
    expected: str
    actual: str


@registry.register
@dataclass(frozen=True)
class ParseTemplateConfigValue(DiagnosticDeclaration):
    """模板配置项必须是字面量。"""

    code: ClassVar[str] = 'parse.template_config_value'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}模板配置 {key} 必须是字面量（不支持 $ 引用 / 模板调用）',
        'en-US': '{location_prefix}template config {key} must be a literal (no $ refs / template calls)',
    }
    key: str


@registry.register
@dataclass(frozen=True)
class TemplateDupArgument(DiagnosticDeclaration):
    """模板调用命名参数重复（语法层即报）。"""

    code: ClassVar[str] = 'template.dup_argument'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的命名参数 {arg!r} 重复提供',
        'en-US': '{path_prefix}duplicate named argument {arg!r} for template {template!r}',
    }
    template: str
    arg: str


@registry.register
@dataclass(frozen=True)
class ParseNestingTooDeep(DiagnosticDeclaration):
    """嵌套层级超限。"""

    code: ClassVar[str] = 'parse.nesting_too_deep'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}嵌套层级超过上限 {limit}，深层内容被跳过',
        'en-US': '{location_prefix}nesting depth exceeds limit {limit}; deeper content skipped',
    }
    limit: int


@registry.register
@dataclass(frozen=True)
class ParseStringIdentifierMisplaced(DiagnosticDeclaration):
    """字符串标识符出现在字段名以外的位置。"""

    code: ClassVar[str] = 'parse.string_identifier_misplaced'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}字符串标识符 {name!r} 只能作为字段名使用',
        'en-US': '{location_prefix}string identifier {name!r} is only valid as a field name',
    }
    name: str
