"""语义分析阶段诊断声明（``template.*`` / ``constraint.*`` / ``import.*`` 等）。

每个诊断 = 一个 ``@dataclass(frozen=True)`` 声明类：``code`` / ``severity`` /
``templates`` 为 ``ClassVar``，字段为类型化渲染参数。导入本模块即完成注册。

原 ``error.generic`` 已删除：parser 已报具体 ``parse.*`` 码，语义层不再重复报告
（``ErrorConstraint`` / ``ErrorValue`` 仅为恢复节点内部载荷）。
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import PurePath
from typing import ClassVar, Mapping

from infinity_data.infra.diagnostics import DiagnosticDeclaration, Severity, registry

__all__ = [
    'Scalar',
    'TemplateShadowsBuiltin',
    'TemplateDuplicate',
    'TemplateRequiredOrder',
    'TemplateImportDepth',
    'TemplateReadFailed',
    'TemplateRecursiveDefault',
    'TemplateImportNotFound',
    'TemplateImportConflictLocal',
    'TemplateImportDuplicate',
    'TemplateUndefined',
    'TemplateMissingRequired',
    'TemplateArgConflict',
    'TemplateVariadicTargetMissing',
    'TemplateVariadicPositionalConflict',
    'TemplateExpandNotList',
    'TemplateExpandLengthMismatch',
    'TemplateExpandTooLarge',
    'TemplateExpandNoSource',
    'TemplateTooManyPositional',
    'TemplatePositionalDisabled',
    'TemplateUnknownArgument',
    'TemplateExpectValue',
    'TemplateExpectObject',
    'TemplateNullUseNullable',
    'TemplateExtraField',
    'TemplateMissingField',
    'TemplateMissingOptional',
    'FieldMissingValue',
    'ValueNestingDepth',
    'ValueNoexistInArray',
    'DictDuplicateKey',
    'UnpackTypeError',
    'VarCycle',
    'VarPathFailed',
    'DollarUndefined',
    'DollarConvertFailed',
    'DollarConvertUnsupported',
    'InftNotAllowed',
    'ConstraintInvalid',
    'ConstraintUnknown',
    'ConstraintArgCount',
    'ConstraintExpectValue',
    'ConstraintTypeMismatch',
    'ConstraintNumericOnly',
    'ConstraintNanNotAllowed',
    'ConstraintRangeArg',
    'ConstraintRangeBelow',
    'ConstraintRangeAbove',
    'ConstraintSizeOnly',
    'ConstraintSizeArg',
    'ConstraintSizeOut',
    'ConstraintEachNeed',
    'ConstraintEachOnly',
    'ConstraintPositionOnly',
    'ConstraintPositionIndex',
    'ConstraintPositionNeed',
    'ConstraintPositionOut',
    'ConstraintInNotIn',
    'ConstraintStringOnly',
    'ConstraintInvalidValue',
    'ConstraintInvalidPath',
    'ConstraintPathDenied',
    'ConstraintPathNotExist',
    'ConstraintPathNotDir',
    'ConstraintPathNotFile',
    'ConstraintPathNotLink',
    'ConstraintSameTargetArg',
    'ConstraintSameTargetMismatch',
    'ConstraintSameNameArg',
    'ConstraintSameNameMismatch',
    'ConstraintExtensionArg',
    'ConstraintExtensionMismatch',
    'ConstraintRegexNoMatch',
    'ConstraintRegexInvalid',
    'ConstraintPositiveFail',
    'ConstraintNegativeFail',
    'ConstraintNonnegativeFail',
    'ConstraintEqMismatch',
    'ConstraintUniqueOnly',
    'ConstraintUniqueDup',
    'ConstraintHasOnly',
    'ConstraintHasMissing',
    'ConstraintFieldOnly',
    'ConstraintFieldNeed',
    'ConstraintFieldMissing',
    'ConstraintNotNeed',
    'ConstraintNotFail',
    'ConstraintAnyFail',
    'ConstraintOneNone',
    'ConstraintOneMany',
    'ConstraintAllFail',
    'ConstraintWhenNeed',
    'ImportFileDenied',
    'ImportFileMissing',
    'ImportPathFailed',
    'ImportTemplateDenied',
    'ImportYamlMissing',
    'ImportUnsupportedFormat',
    'ImportParseFailed',
    'NamespaceDuplicate',
]

Scalar = str | int | bool | Decimal | PurePath
"""诊断参数的标量联合类型（禁止 ``Any`` / ``object`` 兜底）。"""


# ═══════════════════════════════════════════════════════════
# 模板
# ═══════════════════════════════════════════════════════════


@registry.register
@dataclass(frozen=True)
class TemplateShadowsBuiltin(DiagnosticDeclaration):
    """模板与内置约束同名。"""

    code: ClassVar[str] = 'template.shadows_builtin'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 与内置约束同名，禁止定义（避免遮蔽 {template} 约束）',
        'en-US': '{path_prefix}template {template!r} shadows a built-in constraint; definition is forbidden',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateDuplicate(DiagnosticDeclaration):
    """同一文件内模板重复定义。"""

    code: ClassVar[str] = 'template.duplicate'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 重复定义（同一文件内不允许同名模板），后者被拒绝',
        'en-US': '{path_prefix}template {template!r} is defined twice (duplicate names are not allowed); later one rejected',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateRequiredOrder(DiagnosticDeclaration):
    """必填字段出现在可选字段之后。"""

    code: ClassVar[str] = 'template.required_order'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 中必填字段 {field!r} 出现在可选字段之后',
        'en-US': '{path_prefix}required field {field!r} of template {template!r} follows an optional field',
    }
    template: str
    field: str


@registry.register
@dataclass(frozen=True)
class TemplateImportDepth(DiagnosticDeclaration):
    """模板导入嵌套深度超限。"""

    code: ClassVar[str] = 'template.import_depth'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板导入嵌套深度超过上限 {max}: {path_src}',
        'en-US': '{path_prefix}template import depth exceeds limit {max}: {path_src}',
    }
    max: int
    path_src: str


@registry.register
@dataclass(frozen=True)
class TemplateReadFailed(DiagnosticDeclaration):
    """模板文件读取失败。"""

    code: ClassVar[str] = 'template.read_failed'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}读取模板文件失败 {file}: {error}',
        'en-US': '{path_prefix}failed to read template file {file}: {error}',
    }
    file: str
    error: str


@registry.register
@dataclass(frozen=True)
class TemplateRecursiveDefault(DiagnosticDeclaration):
    """模板默认值递归引用。"""

    code: ClassVar[str] = 'template.recursive_default'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的默认值形成递归引用（默认值禁止自引用，展开会无限循环）',
        'en-US': '{path_prefix}template {template!r} has a recursive default (self-reference is forbidden; expansion would loop)',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateImportNotFound(DiagnosticDeclaration):
    """导入文件中不存在模板。"""

    code: ClassVar[str] = 'template.import_not_found'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}导入文件中不存在模板 {template!r}',
        'en-US': '{path_prefix}template {template!r} does not exist in the imported file',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateImportConflictLocal(DiagnosticDeclaration):
    """导入模板与文件内定义冲突。"""

    code: ClassVar[str] = 'template.import_conflict_local'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}导入的模板 {visible!r} 与文件内定义冲突',
        'en-US': '{path_prefix}imported template {visible!r} conflicts with a local definition',
    }
    visible: str


@registry.register
@dataclass(frozen=True)
class TemplateImportDuplicate(DiagnosticDeclaration):
    """可见名重复导入。"""

    code: ClassVar[str] = 'template.import_duplicate'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}可见名 {visible!r} 重复导入（同一 scope 内不允许重复可见名），后者被拒绝',
        'en-US': '{path_prefix}visible name {visible!r} is imported twice in the same scope; later one rejected',
    }
    visible: str


@registry.register
@dataclass(frozen=True)
class TemplateUndefined(DiagnosticDeclaration):
    """未定义的模板。"""

    code: ClassVar[str] = 'template.undefined'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}未定义的模板 {template!r}',
        'en-US': '{path_prefix}undefined template: {template!r}',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateMissingRequired(DiagnosticDeclaration):
    """模板必填字段未提供。"""

    code: ClassVar[str] = 'template.missing_required'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的必填字段 {field!r} 未提供',
        'en-US': '{path_prefix}required field {field!r} of template {template!r} is missing',
    }
    template: str
    field: str


@registry.register
@dataclass(frozen=True)
class TemplateArgConflict(DiagnosticDeclaration):
    """同一字段同时以位置与命名参数提供。"""

    code: ClassVar[str] = 'template.arg_conflict'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 字段 {field!r} 同时以位置和命名参数提供',
        'en-US': '{path_prefix}field {field!r} of template {template!r} is provided both positionally and by name',
    }
    template: str
    field: str


@registry.register
@dataclass(frozen=True)
class TemplateVariadicTargetMissing(DiagnosticDeclaration):
    """收集配置引用了未声明字段。"""

    code: ClassVar[str] = 'template.variadic_target_missing'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的收集配置引用了未声明字段 {field!r}（extra_*_vars 指向的字段必须在模板中声明）',
        'en-US': '{path_prefix}template {template!r} variadic config references undeclared field {field!r}',
    }
    template: str
    field: str


@registry.register
@dataclass(frozen=True)
class TemplateVariadicPositionalConflict(DiagnosticDeclaration):
    """收集配置与 positional=false 冲突。"""

    code: ClassVar[str] = 'template.variadic_positional_conflict'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的 extra_positional_vars 与 positional=false 冲突',
        'en-US': '{path_prefix}template {template!r} combines extra_positional_vars with positional=false',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateExpandNotList(DiagnosticDeclaration):
    """展开轴不是 list。"""

    code: ClassVar[str] = 'template.expand_not_list'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的展开轴必须是 list，实际类型不符',
        'en-US': '{path_prefix}expand axis of template {template!r} must be a list',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateExpandLengthMismatch(DiagnosticDeclaration):
    """展开轴长度不一致。"""

    code: ClassVar[str] = 'template.expand_length_mismatch'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的展开轴长度不一致: {lens}',
        'en-US': '{path_prefix}template {template!r} expand axes have mismatched lengths: {lens}',
    }
    template: str
    lens: list[int]


@registry.register
@dataclass(frozen=True)
class TemplateExpandTooLarge(DiagnosticDeclaration):
    """展开实例总数超限。"""

    code: ClassVar[str] = 'template.expand_too_large'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的展开实例总数 {count} 超过上限 {max}',
        'en-US': '{path_prefix}template {template!r} expands to {count} instances, exceeding limit {max}',
    }
    template: str
    count: int
    max: int


@registry.register
@dataclass(frozen=True)
class TemplateExpandNoSource(DiagnosticDeclaration):
    """调用级展开没有展开源。"""

    code: ClassVar[str] = 'template.expand_no_source'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的调用级 ^ / ... 没有展开源（自身无轴、也无内层传播而来）',
        'en-US': '{path_prefix}template {template!r} call-level ^ / ... has no expand source',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateTooManyPositional(DiagnosticDeclaration):
    """位置参数过多。"""

    code: ClassVar[str] = 'template.too_many_positional'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 只有 {count} 个必填字段，提供了 {given} 个位置参数',
        'en-US': '{path_prefix}template {template!r} has only {count} required fields but {given} positional arguments were given',
    }
    template: str
    count: int
    given: int


@registry.register
@dataclass(frozen=True)
class TemplatePositionalDisabled(DiagnosticDeclaration):
    """模板禁用位置参数。"""

    code: ClassVar[str] = 'template.positional_disabled'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 禁用位置参数，请使用命名参数',
        'en-US': '{path_prefix}template {template!r} disables positional arguments; use named arguments',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateUnknownArgument(DiagnosticDeclaration):
    """未知命名参数。"""

    code: ClassVar[str] = 'template.unknown_argument'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 收到未知命名参数 {arg!r}',
        'en-US': '{path_prefix}template {template!r} received unknown named argument {arg!r}',
    }
    template: str
    arg: str


@registry.register
@dataclass(frozen=True)
class TemplateExpectValue(DiagnosticDeclaration):
    """模板约束期望值。"""

    code: ClassVar[str] = 'template.expect_value'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}期望 {template}（模板约束），实际没有值',
        'en-US': '{path_prefix}expected {template} (template constraint), got no value',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateExpectObject(DiagnosticDeclaration):
    """模板约束期望对象。"""

    code: ClassVar[str] = 'template.expect_object'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}期望 {template}（对象），实际 {actual}',
        'en-US': '{path_prefix}expected {template} (object), got {actual}',
    }
    template: str
    actual: str


@registry.register
@dataclass(frozen=True)
class TemplateNullUseNullable(DiagnosticDeclaration):
    """模板约束遇到 null。"""

    code: ClassVar[str] = 'template.null_use_nullable'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}期望 {template}，实际 null（使用 {template}? 允许可空）',
        'en-US': '{path_prefix}expected {template}, got null (use {template}? to allow null)',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class TemplateExtraField(DiagnosticDeclaration):
    """模板不允许额外字段。"""

    code: ClassVar[str] = 'template.extra_field'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template} 不允许额外字段 {field!r}',
        'en-US': '{path_prefix}template {template} does not allow extra field {field!r}',
    }
    template: str
    field: str


@registry.register
@dataclass(frozen=True)
class TemplateMissingField(DiagnosticDeclaration):
    """模板必填字段缺失。"""

    code: ClassVar[str] = 'template.missing_field'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template} 的必填字段 {field!r} 缺失',
        'en-US': '{path_prefix}required field {field!r} of template {template} is missing',
    }
    template: str
    field: str


@registry.register
@dataclass(frozen=True)
class TemplateMissingOptional(DiagnosticDeclaration):
    """模板可选字段缺失（完整形状要求）。"""

    code: ClassVar[str] = 'template.missing_optional'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板 {template!r} 的可选字段 {field!r} 缺失（完整形状要求声明字段；用 `!` 允许缺失）',
        'en-US': '{path_prefix}optional field {field!r} of template {template!r} is missing (declare it, or use `!` to allow absence)',
    }
    template: str
    field: str


# ═══════════════════════════════════════════════════════════
# 字段 / 值 / $ 引用
# ═══════════════════════════════════════════════════════════


@registry.register
@dataclass(frozen=True)
class FieldMissingValue(DiagnosticDeclaration):
    """字段缺少值。"""

    code: ClassVar[str] = 'field.missing_value'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}字段缺少值（如需 noexist 请显式书写 = noexist）',
        'en-US': '{path_prefix}field is missing a value (write = noexist explicitly if intended)',
    }


@registry.register
@dataclass(frozen=True)
class ValueNestingDepth(DiagnosticDeclaration):
    """值嵌套层级超限。"""

    code: ClassVar[str] = 'value.nesting_depth'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}嵌套层级超过上限 {max}',
        'en-US': '{path_prefix}nesting depth exceeds limit {max}',
    }
    max: int


@registry.register
@dataclass(frozen=True)
class ValueNoexistInArray(DiagnosticDeclaration):
    """数组元素使用 noexist。"""

    code: ClassVar[str] = 'value.noexist_in_array'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}noexist 仅用于 dict 字段，数组元素中无意义（如需空位请用 null）',
        'en-US': '{path_prefix}noexist is only for dict fields; meaningless in array elements (use null for a slot)',
    }


@registry.register
@dataclass(frozen=True)
class DictDuplicateKey(DiagnosticDeclaration):
    """dict 重复键。"""

    code: ClassVar[str] = 'dict.duplicate_key'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}键 {name!r} 重复定义（同一 dict 内不允许同名键），保留先到者',
        'en-US': '{path_prefix}duplicate key {name!r} (duplicate keys are not allowed in a dict); first wins',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class UnpackTypeError(DiagnosticDeclaration):
    """解包目标类型错误。"""

    code: ClassVar[str] = 'unpack.type_error'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}解包目标必须是 {want}（** 为 dict，* 为 list），实际类型不符',
        'en-US': '{path_prefix}unpack target must be {want} (** is dict, * is list)',
    }
    want: str


@registry.register
@dataclass(frozen=True)
class VarCycle(DiagnosticDeclaration):
    """!var 循环依赖。"""

    code: ClassVar[str] = 'var.cycle'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}!var 别名 {alias!r} 形成循环依赖（前向引用不允许环）',
        'en-US': '{path_prefix}!var alias {alias!r} forms a dependency cycle',
    }
    alias: str


@registry.register
@dataclass(frozen=True)
class VarPathFailed(DiagnosticDeclaration):
    """!var 路径取不到目标。"""

    code: ClassVar[str] = 'var.path_failed'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}!var 别名 {alias!r} 的 JSON path 取不到目标',
        'en-US': '{path_prefix}JSON path of !var alias {alias!r} does not resolve',
    }
    alias: str


@registry.register
@dataclass(frozen=True)
class DollarUndefined(DiagnosticDeclaration):
    """未找到导入变量。"""

    code: ClassVar[str] = 'dollar.undefined'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}未找到导入变量 ${name}',
        'en-US': '{path_prefix}undefined import variable ${name}',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class DollarConvertFailed(DiagnosticDeclaration):
    """$ 引用类型转换失败。"""

    code: ClassVar[str] = 'dollar.convert_failed'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}无法将 ${name}={raw!r} 转为 {type}',
        'en-US': '{path_prefix}cannot convert ${name}={raw!r} to {type}',
    }
    name: str
    raw: Scalar | None
    type: str


@registry.register
@dataclass(frozen=True)
class DollarConvertUnsupported(DiagnosticDeclaration):
    """结构化值不支持 as 转换。"""

    code: ClassVar[str] = 'dollar.convert_unsupported'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}结构化值 ${name}（{kind}）不支持 as {type} 转换，已原样保留',
        'en-US': '{path_prefix}structured value ${name} ({kind}) does not support as {type}; kept as-is',
    }
    name: str
    kind: str
    type: str


@registry.register
@dataclass(frozen=True)
class InftNotAllowed(DiagnosticDeclaration):
    """.inft 文件包含非模板语句。"""

    code: ClassVar[str] = 'inft.not_allowed'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}.inft 文件只允许模板定义，发现其他语句',
        'en-US': '{path_prefix}.inft files may only contain template definitions',
    }


# ═══════════════════════════════════════════════════════════
# 约束引擎
# ═══════════════════════════════════════════════════════════


@registry.register
@dataclass(frozen=True)
class ConstraintInvalid(DiagnosticDeclaration):
    """无效的约束表达式。"""

    code: ClassVar[str] = 'constraint.invalid'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}无效的约束表达式',
        'en-US': '{path_prefix}invalid constraint expression',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintUnknown(DiagnosticDeclaration):
    """未知约束。"""

    code: ClassVar[str] = 'constraint.unknown'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}未知约束 {name!r}',
        'en-US': '{path_prefix}unknown constraint {name!r}',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class ConstraintArgCount(DiagnosticDeclaration):
    """约束参数个数不符。"""

    code: ClassVar[str] = 'constraint.arg_count'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}约束 {name}() 期望 {expected} 个参数，实际 {given} 个',
        'en-US': '{path_prefix}constraint {name}() expects {expected} argument(s), got {given}',
    }
    name: str
    expected: str
    given: int


@registry.register
@dataclass(frozen=True)
class ConstraintExpectValue(DiagnosticDeclaration):
    """约束期望有值。"""

    code: ClassVar[str] = 'constraint.expect_value'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}期望 {expected}，实际没有值',
        'en-US': '{path_prefix}expected {expected}, got no value',
    }
    expected: str


@registry.register
@dataclass(frozen=True)
class ConstraintTypeMismatch(DiagnosticDeclaration):
    """约束类型不匹配。"""

    code: ClassVar[str] = 'constraint.type_mismatch'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}期望 {expected}，实际 {actual}',
        'en-US': '{path_prefix}expected {expected}, got {actual}',
    }
    expected: str
    actual: str


@registry.register
@dataclass(frozen=True)
class ConstraintNumericOnly(DiagnosticDeclaration):
    """约束只适用于数值。"""

    code: ClassVar[str] = 'constraint.numeric_only'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}{constraint} 约束只适用于数值，实际 {actual}',
        'en-US': '{path_prefix}{constraint} constraint only applies to numbers, got {actual}',
    }
    constraint: str
    actual: str


@registry.register
@dataclass(frozen=True)
class ConstraintNanNotAllowed(DiagnosticDeclaration):
    """约束不适用于 NaN。"""

    code: ClassVar[str] = 'constraint.nan_not_allowed'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}{constraint} 约束不适用于 NaN',
        'en-US': '{path_prefix}{constraint} constraint does not apply to NaN',
    }
    constraint: str


@registry.register
@dataclass(frozen=True)
class ConstraintRangeArg(DiagnosticDeclaration):
    """range 参数非法。"""

    code: ClassVar[str] = 'constraint.range_arg'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}range 参数必须是数值: {value!r}',
        'en-US': '{path_prefix}range argument must be a number: {value!r}',
    }
    value: Scalar


@registry.register
@dataclass(frozen=True)
class ConstraintRangeBelow(DiagnosticDeclaration):
    """值小于下界。"""

    code: ClassVar[str] = 'constraint.range_below'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}值 {value} 小于下界 {lo}',
        'en-US': '{path_prefix}value {value} is below lower bound {lo}',
    }
    value: Decimal
    lo: Decimal


@registry.register
@dataclass(frozen=True)
class ConstraintRangeAbove(DiagnosticDeclaration):
    """值大于上界。"""

    code: ClassVar[str] = 'constraint.range_above'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}值 {value} 大于上界 {hi}',
        'en-US': '{path_prefix}value {value} exceeds upper bound {hi}',
    }
    value: Decimal
    hi: Decimal


@registry.register
@dataclass(frozen=True)
class ConstraintSizeOnly(DiagnosticDeclaration):
    """size 约束类型错误。"""

    code: ClassVar[str] = 'constraint.size_only'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}size 约束适用于 str/list/dict，实际 {actual}',
        'en-US': '{path_prefix}size constraint applies to str/list/dict, got {actual}',
    }
    actual: str


@registry.register
@dataclass(frozen=True)
class ConstraintSizeArg(DiagnosticDeclaration):
    """size 参数非法。"""

    code: ClassVar[str] = 'constraint.size_arg'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}size 参数必须是整数',
        'en-US': '{path_prefix}size argument must be an integer',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintSizeOut(DiagnosticDeclaration):
    """大小超出范围。"""

    code: ClassVar[str] = 'constraint.size_out'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}大小 {size} 不在范围 [{lo}, {hi}] 内',
        'en-US': '{path_prefix}size {size} is outside range [{lo}, {hi}]',
    }
    size: int
    lo: Decimal
    hi: Decimal | None


@registry.register
@dataclass(frozen=True)
class ConstraintEachNeed(DiagnosticDeclaration):
    """each() 缺少约束参数。"""

    code: ClassVar[str] = 'constraint.each_need'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}each() 需要一个约束参数',
        'en-US': '{path_prefix}each() requires a constraint argument',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintEachOnly(DiagnosticDeclaration):
    """each 约束类型错误。"""

    code: ClassVar[str] = 'constraint.each_only'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}each 约束适用于 list/dict，实际 {actual}',
        'en-US': '{path_prefix}each constraint applies to list/dict, got {actual}',
    }
    actual: str


@registry.register
@dataclass(frozen=True)
class ConstraintPositionOnly(DiagnosticDeclaration):
    """position 约束类型错误。"""

    code: ClassVar[str] = 'constraint.position_only'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}position 约束只适用于 list，实际 {actual}',
        'en-US': '{path_prefix}position constraint only applies to list, got {actual}',
    }
    actual: str


@registry.register
@dataclass(frozen=True)
class ConstraintPositionIndex(DiagnosticDeclaration):
    """position 下标非法。"""

    code: ClassVar[str] = 'constraint.position_index'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}position 下标必须是整数: {value!r}',
        'en-US': '{path_prefix}position index must be an integer: {value!r}',
    }
    value: Scalar | None


@registry.register
@dataclass(frozen=True)
class ConstraintPositionNeed(DiagnosticDeclaration):
    """position() 缺少约束参数。"""

    code: ClassVar[str] = 'constraint.position_need'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}position() 需要一个约束参数',
        'en-US': '{path_prefix}position() requires a constraint argument',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintPositionOut(DiagnosticDeclaration):
    """position 下标越界。"""

    code: ClassVar[str] = 'constraint.position_out'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}下标 {index} 越界（list 大小 {size}）',
        'en-US': '{path_prefix}index {index} is out of range (list size {size})',
    }
    index: int
    size: int


@registry.register
@dataclass(frozen=True)
class ConstraintInNotIn(DiagnosticDeclaration):
    """值不在允许集合中。"""

    code: ClassVar[str] = 'constraint.in_not_in'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}值 {value} 不在允许的值 {choices!r} 中',
        'en-US': '{path_prefix}value {value} is not one of {choices!r}',
    }
    value: str
    choices: list[Scalar]


@registry.register
@dataclass(frozen=True)
class ConstraintStringOnly(DiagnosticDeclaration):
    """约束只适用于字符串。"""

    code: ClassVar[str] = 'constraint.string_only'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}{constraint} 约束只适用于字符串',
        'en-US': '{path_prefix}{constraint} constraint only applies to strings',
    }
    constraint: str


@registry.register
@dataclass(frozen=True)
class ConstraintInvalidValue(DiagnosticDeclaration):
    """无效值。"""

    code: ClassVar[str] = 'constraint.invalid_value'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}无效的{what} {value!r}',
        'en-US': '{path_prefix}invalid {what} {value!r}',
    }
    what: str
    value: str


@registry.register
@dataclass(frozen=True)
class ConstraintInvalidPath(DiagnosticDeclaration):
    """无效路径值。"""

    code: ClassVar[str] = 'constraint.invalid_path'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}无效的路径 {value!r}（path 约束：非空、无 NUL、可解析）',
        'en-US': '{path_prefix}invalid path {value!r} (path: non-empty, no NUL, parseable)',
    }
    value: str


@registry.register
@dataclass(frozen=True)
class ConstraintPathDenied(DiagnosticDeclaration):
    """路径超出沙盒授权。"""

    code: ClassVar[str] = 'constraint.path_denied'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}{constraint} 约束目标 {path!r} 超出沙盒授权（allow_files 白名单外），已拒绝',
        'en-US': '{path_prefix}{constraint} target {path!r} is outside sandbox authorization (allow_files); denied',
    }
    constraint: str
    path: str


@registry.register
@dataclass(frozen=True)
class ConstraintPathNotExist(DiagnosticDeclaration):
    """路径不存在。"""

    code: ClassVar[str] = 'constraint.path_not_exist'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}路径 {path!r} 不存在',
        'en-US': '{path_prefix}path {path!r} does not exist',
    }
    path: str


@registry.register
@dataclass(frozen=True)
class ConstraintPathNotDir(DiagnosticDeclaration):
    """路径不是目录。"""

    code: ClassVar[str] = 'constraint.path_not_dir'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}路径 {path!r} 不是目录',
        'en-US': '{path_prefix}path {path!r} is not a directory',
    }
    path: str


@registry.register
@dataclass(frozen=True)
class ConstraintPathNotFile(DiagnosticDeclaration):
    """路径不是普通文件。"""

    code: ClassVar[str] = 'constraint.path_not_file'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}路径 {path!r} 不是普通文件',
        'en-US': '{path_prefix}path {path!r} is not a regular file',
    }
    path: str


@registry.register
@dataclass(frozen=True)
class ConstraintPathNotLink(DiagnosticDeclaration):
    """路径不是符号链接。"""

    code: ClassVar[str] = 'constraint.path_not_link'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}路径 {path!r} 不是符号链接',
        'en-US': '{path_prefix}path {path!r} is not a symbolic link',
    }
    path: str


@registry.register
@dataclass(frozen=True)
class ConstraintSameTargetArg(DiagnosticDeclaration):
    """same_target 参数类型错误。"""

    code: ClassVar[str] = 'constraint.same_target_arg'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}same_target 参数必须是 path 字面量，实际 {expected}',
        'en-US': '{path_prefix}same_target argument must be a path literal, got {expected}',
    }
    expected: str


@registry.register
@dataclass(frozen=True)
class ConstraintSameTargetMismatch(DiagnosticDeclaration):
    """same_target 不匹配。"""

    code: ClassVar[str] = 'constraint.same_target_mismatch'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}路径 {value!r} 与期望 {expected!r} 词法解析后不同 target',
        'en-US': '{path_prefix}path {value!r} and expected {expected!r} resolve to different targets',
    }
    value: str
    expected: str


@registry.register
@dataclass(frozen=True)
class ConstraintSameNameArg(DiagnosticDeclaration):
    """same_name 参数类型错误。"""

    code: ClassVar[str] = 'constraint.same_name_arg'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}same_name 参数必须是字符串，实际 {expected}',
        'en-US': '{path_prefix}same_name argument must be a string, got {expected}',
    }
    expected: str


@registry.register
@dataclass(frozen=True)
class ConstraintSameNameMismatch(DiagnosticDeclaration):
    """same_name 不匹配。"""

    code: ClassVar[str] = 'constraint.same_name_mismatch'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}路径 basename {name!r} 不等于期望 {expected!r}',
        'en-US': '{path_prefix}path basename {name!r} does not equal {expected!r}',
    }
    name: str
    expected: str


@registry.register
@dataclass(frozen=True)
class ConstraintExtensionArg(DiagnosticDeclaration):
    """extension 参数类型错误。"""

    code: ClassVar[str] = 'constraint.extension_arg'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}extension 参数必须是扩展名字符串（如 "json"），实际 {expected}',
        'en-US': '{path_prefix}extension argument must be an extension string (e.g. "json"), got {expected}',
    }
    expected: str


@registry.register
@dataclass(frozen=True)
class ConstraintExtensionMismatch(DiagnosticDeclaration):
    """扩展名不匹配。"""

    code: ClassVar[str] = 'constraint.extension_mismatch'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}路径扩展名 {suffix} 不在期望 {expected!r} 中',
        'en-US': '{path_prefix}path extension {suffix} is not in {expected!r}',
    }
    suffix: str
    expected: list[str]


@registry.register
@dataclass(frozen=True)
class ConstraintRegexNoMatch(DiagnosticDeclaration):
    """正则不匹配。"""

    code: ClassVar[str] = 'constraint.regex_no_match'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}值 {value!r} 不匹配正则 {pattern!r}',
        'en-US': '{path_prefix}value {value!r} does not match pattern {pattern!r}',
    }
    value: str
    pattern: str


@registry.register
@dataclass(frozen=True)
class ConstraintRegexInvalid(DiagnosticDeclaration):
    """正则表达式无效。"""

    code: ClassVar[str] = 'constraint.regex_invalid'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}无效的正则表达式 {pattern!r}: {error}',
        'en-US': '{path_prefix}invalid regular expression {pattern!r}: {error}',
    }
    pattern: str
    error: str


@registry.register
@dataclass(frozen=True)
class ConstraintPositiveFail(DiagnosticDeclaration):
    """值不是正数。"""

    code: ClassVar[str] = 'constraint.positive_fail'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}值 {value} 不是正数',
        'en-US': '{path_prefix}value {value} is not positive',
    }
    value: Decimal


@registry.register
@dataclass(frozen=True)
class ConstraintNegativeFail(DiagnosticDeclaration):
    """值不是负数。"""

    code: ClassVar[str] = 'constraint.negative_fail'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}值 {value} 不是负数',
        'en-US': '{path_prefix}value {value} is not negative',
    }
    value: Decimal


@registry.register
@dataclass(frozen=True)
class ConstraintNonnegativeFail(DiagnosticDeclaration):
    """值是负数。"""

    code: ClassVar[str] = 'constraint.nonnegative_fail'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}值 {value} 是负数',
        'en-US': '{path_prefix}value {value} is negative',
    }
    value: Decimal


@registry.register
@dataclass(frozen=True)
class ConstraintEqMismatch(DiagnosticDeclaration):
    """值不相等。"""

    code: ClassVar[str] = 'constraint.eq_mismatch'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}值 {value} 不等于 {expected!r}',
        'en-US': '{path_prefix}value {value} does not equal {expected!r}',
    }
    value: str
    expected: Scalar | list[Scalar] | dict[str, Scalar]


@registry.register
@dataclass(frozen=True)
class ConstraintUniqueOnly(DiagnosticDeclaration):
    """unique 约束类型错误。"""

    code: ClassVar[str] = 'constraint.unique_only'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}unique 约束只适用于 list',
        'en-US': '{path_prefix}unique constraint only applies to list',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintUniqueDup(DiagnosticDeclaration):
    """元素重复。"""

    code: ClassVar[str] = 'constraint.unique_dup'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}元素 {value} 重复',
        'en-US': '{path_prefix}duplicate element {value}',
    }
    value: str


@registry.register
@dataclass(frozen=True)
class ConstraintHasOnly(DiagnosticDeclaration):
    """has 约束类型错误。"""

    code: ClassVar[str] = 'constraint.has_only'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}has 约束只适用于 dict',
        'en-US': '{path_prefix}has constraint only applies to dict',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintHasMissing(DiagnosticDeclaration):
    """缺少键。"""

    code: ClassVar[str] = 'constraint.has_missing'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}缺少键 {key!r}',
        'en-US': '{path_prefix}missing key {key!r}',
    }
    key: str


@registry.register
@dataclass(frozen=True)
class ConstraintFieldOnly(DiagnosticDeclaration):
    """field 约束类型错误。"""

    code: ClassVar[str] = 'constraint.field_only'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}field 约束只适用于 dict',
        'en-US': '{path_prefix}field constraint only applies to dict',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintFieldNeed(DiagnosticDeclaration):
    """field() 缺少约束参数。"""

    code: ClassVar[str] = 'constraint.field_need'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}field() 的第二个参数必须是约束',
        'en-US': '{path_prefix}the second argument of field() must be a constraint',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintFieldMissing(DiagnosticDeclaration):
    """字段不存在。"""

    code: ClassVar[str] = 'constraint.field_missing'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}字段 {field!r} 不存在',
        'en-US': '{path_prefix}field {field!r} does not exist',
    }
    field: str


@registry.register
@dataclass(frozen=True)
class ConstraintNotNeed(DiagnosticDeclaration):
    """not() 缺少约束参数。"""

    code: ClassVar[str] = 'constraint.not_need'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}not() 需要一个约束参数',
        'en-US': '{path_prefix}not() requires a constraint argument',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintNotFail(DiagnosticDeclaration):
    """not 约束失败。"""

    code: ClassVar[str] = 'constraint.not_fail'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}not 约束失败（内部约束意外满足）',
        'en-US': '{path_prefix}not constraint failed (inner constraint unexpectedly satisfied)',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintAnyFail(DiagnosticDeclaration):
    """any 约束失败。"""

    code: ClassVar[str] = 'constraint.any_fail'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}any 约束失败（所有子约束都不满足）',
        'en-US': '{path_prefix}any constraint failed (no child constraint satisfied)',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintOneNone(DiagnosticDeclaration):
    """one 约束无满足项。"""

    code: ClassVar[str] = 'constraint.one_none'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}one 约束失败（没有子约束被满足）',
        'en-US': '{path_prefix}one constraint failed (no child constraint satisfied)',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintOneMany(DiagnosticDeclaration):
    """one 约束多个满足项。"""

    code: ClassVar[str] = 'constraint.one_many'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}one 约束失败（{count} 个子约束被满足: {names}）',
        'en-US': '{path_prefix}one constraint failed ({count} child constraints satisfied: {names})',
    }
    count: int
    names: list[str]


@registry.register
@dataclass(frozen=True)
class ConstraintAllFail(DiagnosticDeclaration):
    """all 约束失败。"""

    code: ClassVar[str] = 'constraint.all_fail'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}all 约束失败',
        'en-US': '{path_prefix}all constraint failed',
    }


@registry.register
@dataclass(frozen=True)
class ConstraintWhenNeed(DiagnosticDeclaration):
    """when() 缺少约束参数。"""

    code: ClassVar[str] = 'constraint.when_need'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}when() 需要两个约束参数',
        'en-US': '{path_prefix}when() requires two constraint arguments',
    }


# ═══════════════════════════════════════════════════════════
# 导入
# ═══════════════════════════════════════════════════════════


@registry.register
@dataclass(frozen=True)
class ImportFileDenied(DiagnosticDeclaration):
    """文件导入超出沙盒授权。"""

    code: ClassVar[str] = 'import.file_denied'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}文件导入超出沙盒授权，已忽略: {path_src}',
        'en-US': '{path_prefix}file import denied by sandbox, ignored: {path_src}',
    }
    path_src: str


@registry.register
@dataclass(frozen=True)
class ImportFileMissing(DiagnosticDeclaration):
    """导入文件不存在。"""

    code: ClassVar[str] = 'import.file_missing'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}导入文件不存在: {name}',
        'en-US': '{path_prefix}imported file does not exist: {name}',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class ImportPathFailed(DiagnosticDeclaration):
    """导入路径解析失败。"""

    code: ClassVar[str] = 'import.path_failed'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}无法解析导入路径: {name}',
        'en-US': '{path_prefix}cannot resolve import path: {name}',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class ImportTemplateDenied(DiagnosticDeclaration):
    """模板导入超出沙盒授权。"""

    code: ClassVar[str] = 'import.template_denied'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}模板导入超出沙盒授权，已忽略: {path_src}',
        'en-US': '{path_prefix}template import denied by sandbox, ignored: {path_src}',
    }
    path_src: str


@registry.register
@dataclass(frozen=True)
class ImportYamlMissing(DiagnosticDeclaration):
    """缺少 PyYAML。"""

    code: ClassVar[str] = 'import.yaml_missing'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}yaml 支持需要安装 PyYAML',
        'en-US': '{path_prefix}yaml support requires PyYAML',
    }


@registry.register
@dataclass(frozen=True)
class ImportUnsupportedFormat(DiagnosticDeclaration):
    """不支持的文件格式。"""

    code: ClassVar[str] = 'import.unsupported_format'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}不支持的文件格式: {format}',
        'en-US': '{path_prefix}unsupported file format: {format}',
    }
    format: str


@registry.register
@dataclass(frozen=True)
class ImportParseFailed(DiagnosticDeclaration):
    """解析导入数据失败。"""

    code: ClassVar[str] = 'import.parse_failed'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}解析数据失败: {error}',
        'en-US': '{path_prefix}failed to parse imported data: {error}',
    }
    error: str


@registry.register
@dataclass(frozen=True)
class NamespaceDuplicate(DiagnosticDeclaration):
    """导入别名重复绑定。"""

    code: ClassVar[str] = 'namespace.duplicate'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}导入别名 {name!r} 重复绑定（$ 命名空间内不允许重复），后者被拒绝',
        'en-US': '{path_prefix}import alias {name!r} is bound twice in the $ namespace; later one rejected',
    }
    name: str
