"""语义分析阶段诊断定义（集中注册）。

语义层的全部诊断定义（``template.*`` / ``constraint.*`` / ``field.*`` /
``value.*`` / ``dollar.*`` / ``import.*`` / ``namespace.*`` 等）在此集中，
导入时经 :func:`register_diagnostic_define` 合并进全局注册表。

与词法（``tokenizer/diagnostics.py``）、语法（``parser/diagnostics.py``）一致：
**每层一个诊断词汇表文件**，便于审计与多语言维护。
"""

from infinity_data.infra.diagnostics import diagnostic_define, register_diagnostic_define

register_diagnostic_define(
    # ═══════════════════════════════════════════════════════════
    # 模板
    # ═══════════════════════════════════════════════════════════
    diagnostic_define(
        'template.shadows_builtin',
        '{path_prefix}模板 {template!r} 与内置约束同名，禁止定义（避免遮蔽 {template} 约束）',
    ),
    diagnostic_define(
        'template.duplicate', '{path_prefix}模板 {template!r} 重复定义（同一文件内不允许同名模板），后者被拒绝'
    ),
    diagnostic_define(
        'template.required_order', '{path_prefix}模板 {template!r} 中必填字段 {field!r} 出现在可选字段之后'
    ),
    diagnostic_define('template.import_depth', '{path_prefix}模板导入嵌套深度超过上限 {max}: {path_src}'),
    diagnostic_define('template.read_failed', '{path_prefix}读取模板文件失败 {file}: {error}'),
    diagnostic_define(
        'template.recursive_default',
        '{path_prefix}模板 {template!r} 的默认值形成递归引用（默认值禁止自引用，展开会无限循环）',
        en='{path_prefix}template {template!r} has a recursive default (self-reference in defaults is forbidden; expansion would loop forever)',
    ),
    diagnostic_define('template.import_not_found', '{path_prefix}导入文件中不存在模板 {template!r}'),
    diagnostic_define('template.import_conflict_local', '{path_prefix}导入的模板 {visible!r} 与文件内定义冲突'),
    diagnostic_define(
        'template.import_duplicate',
        '{path_prefix}可见名 {visible!r} 重复导入（同一 scope 内不允许重复可见名），后者被拒绝',
    ),
    diagnostic_define(
        'template.undefined',
        '{path_prefix}未定义的模板 {template!r}',
        en='{path_prefix}undefined template: {template!r}',
    ),
    diagnostic_define(
        'template.missing_required',
        '{path_prefix}模板 {template!r} 的必填字段 {field!r} 未提供',
        en='{path_prefix}required field {field!r} of template {template!r} is missing',
    ),
    diagnostic_define(
        'template.arg_conflict', '{path_prefix}模板 {template!r} 字段 {field!r} 同时以位置和命名参数提供'
    ),
    diagnostic_define(
        'template.dup_argument',
        '{path_prefix}模板 {template!r} 的命名参数 {arg!r} 重复提供',
        en='{path_prefix}duplicate named argument {arg!r} for template {template!r}',
    ),
    diagnostic_define(
        'template.variadic_target_missing',
        '{path_prefix}模板 {template!r} 的收集配置引用了未声明字段 {field!r}（extra_*_vars 指向的字段必须在模板中声明）',
    ),
    diagnostic_define(
        'template.variadic_positional_conflict',
        '{path_prefix}模板 {template!r} 的 extra_positional_vars 与 positional=false 冲突',
    ),
    diagnostic_define(
        'template.expand_not_list',
        '{path_prefix}模板 {template!r} 的展开轴必须是 list，实际类型不符',
        en='{path_prefix}expand axis of template {template!r} must be a list',
    ),
    diagnostic_define(
        'template.expand_length_mismatch',
        '{path_prefix}模板 {template!r} 的展开轴长度不一致: {lens}',
    ),
    diagnostic_define(
        'template.expand_too_large',
        '{path_prefix}模板 {template!r} 的展开实例总数 {count} 超过上限 {max}',
    ),
    diagnostic_define(
        'template.expand_no_source',
        '{path_prefix}模板 {template!r} 的调用级 ... 没有展开源（自身无轴、也无内层传播而来）',
    ),
    diagnostic_define(
        'template.too_many_positional',
        '{path_prefix}模板 {template!r} 只有 {count} 个必填字段，提供了 {given} 个位置参数',
    ),
    diagnostic_define(
        'template.positional_disabled',
        '{path_prefix}模板 {template!r} 禁用位置参数，请使用命名参数',
        en='{path_prefix}template {template!r} disables positional arguments; use named arguments',
    ),
    diagnostic_define(
        'template.unknown_argument',
        '{path_prefix}模板 {template!r} 收到未知命名参数 {arg!r}',
        en='{path_prefix}template {template!r} received unknown named argument {arg!r}',
    ),
    diagnostic_define('template.expect_value', '{path_prefix}期望 {template}（模板约束），实际没有值'),
    diagnostic_define('template.expect_object', '{path_prefix}期望 {template}（对象），实际 {actual}'),
    diagnostic_define(
        'template.null_use_nullable', '{path_prefix}期望 {template}，实际 null（使用 {template}? 允许可空）'
    ),
    diagnostic_define('template.extra_field', '{path_prefix}模板 {template} 不允许额外字段 {field!r}'),
    diagnostic_define('template.missing_field', '{path_prefix}模板 {template} 的必填字段 {field!r} 缺失'),
    # ═══════════════════════════════════════════════════════════
    # 字段 / 值 / $ 引用
    # ═══════════════════════════════════════════════════════════
    diagnostic_define(
        'field.missing_value',
        '{path_prefix}字段缺少值（如需 noexist 请显式书写 = noexist）',
        en='{path_prefix}field is missing a value (write = noexist explicitly if intended)',
    ),
    diagnostic_define('value.nesting_depth', '{path_prefix}嵌套层级超过上限 {max}'),
    diagnostic_define(
        'value.noexist_in_array',
        '{path_prefix}noexist 仅用于 dict 字段，数组元素中无意义（如需空位请用 null）',
        en='{path_prefix}noexist is only for dict fields; meaningless in array elements (use null for a slot)',
    ),
    diagnostic_define(
        'dict.duplicate_key',
        '{path_prefix}键 {name!r} 重复定义（同一 dict 内不允许同名键），保留先到者',
        en='{path_prefix}duplicate key {name!r} (duplicate keys are not allowed in a dict); first wins',
    ),
    diagnostic_define(
        'unpack.type_error',
        '{path_prefix}解包目标必须是 {want}（** 为 dict，* 为 list），实际类型不符',
        en='{path_prefix}unpack target must be {want} (** is dict, * is list)',
    ),
    diagnostic_define('var.cycle', '{path_prefix}!var 别名 {alias!r} 形成循环依赖（前向引用不允许环）'),
    diagnostic_define('var.path_failed', '{path_prefix}!var 别名 {alias!r} 的 JSON path 取不到目标'),
    diagnostic_define(
        'dollar.undefined', '{path_prefix}未找到导入变量 ${name}', en='{path_prefix}undefined import variable ${name}'
    ),
    diagnostic_define(
        'dollar.convert_failed',
        '{path_prefix}无法将 ${name}={raw!r} 转为 {type}',
        en='{path_prefix}cannot convert ${name}={raw!r} to {type}',
    ),
    diagnostic_define('inft.not_allowed', '{path_prefix}.inft 文件只允许模板定义，发现其他语句'),
    diagnostic_define('error.generic', '{path_prefix}{message}'),
    # ═══════════════════════════════════════════════════════════
    # 约束引擎
    # ═══════════════════════════════════════════════════════════
    diagnostic_define('constraint.invalid', '{path_prefix}无效的约束表达式'),
    diagnostic_define('constraint.unknown', '{path_prefix}未知约束 {name!r}'),
    diagnostic_define('constraint.arg_count', '{path_prefix}约束 {name}() 期望 {expected} 个参数，实际 {given} 个'),
    diagnostic_define(
        'constraint.expect_value',
        '{path_prefix}期望 {expected}，实际没有值',
        en='{path_prefix}expected {expected}, got no value',
    ),
    diagnostic_define(
        'constraint.type_mismatch',
        '{path_prefix}期望 {expected}，实际 {actual}',
        en='{path_prefix}expected {expected}, got {actual}',
    ),
    diagnostic_define('constraint.numeric_only', '{path_prefix}{constraint} 约束只适用于数值，实际 {actual}'),
    diagnostic_define('constraint.nan_not_allowed', '{path_prefix}{constraint} 约束不适用于 NaN'),
    diagnostic_define('constraint.range_arg', '{path_prefix}range 参数必须是数值: {value!r}'),
    diagnostic_define(
        'constraint.range_below',
        '{path_prefix}值 {value} 小于下界 {lo}',
        en='{path_prefix}value {value} is below lower bound {lo}',
    ),
    diagnostic_define(
        'constraint.range_above',
        '{path_prefix}值 {value} 大于上界 {hi}',
        en='{path_prefix}value {value} exceeds upper bound {hi}',
    ),
    diagnostic_define('constraint.size_only', '{path_prefix}size 约束适用于 str/list/dict，实际 {actual}'),
    diagnostic_define('constraint.size_arg', '{path_prefix}size 参数必须是整数'),
    diagnostic_define('constraint.size_out', '{path_prefix}大小 {size} 不在范围 [{lo}, {hi}] 内'),
    diagnostic_define('constraint.each_need', '{path_prefix}each() 需要一个约束参数'),
    diagnostic_define('constraint.each_only', '{path_prefix}each 约束适用于 list/dict，实际 {actual}'),
    diagnostic_define('constraint.in_not_in', '{path_prefix}值 {value} 不在允许的值 {choices!r} 中'),
    diagnostic_define('constraint.string_only', '{path_prefix}{constraint} 约束只适用于字符串'),
    diagnostic_define('constraint.invalid_value', '{path_prefix}无效的{what} {value!r}'),
    diagnostic_define('constraint.regex_no_match', '{path_prefix}值 {value!r} 不匹配正则 {pattern!r}'),
    diagnostic_define('constraint.regex_invalid', '{path_prefix}无效的正则表达式 {pattern!r}: {error}'),
    diagnostic_define('constraint.positive_fail', '{path_prefix}值 {value} 不是正数'),
    diagnostic_define('constraint.negative_fail', '{path_prefix}值 {value} 不是负数'),
    diagnostic_define('constraint.nonnegative_fail', '{path_prefix}值 {value} 是负数'),
    diagnostic_define(
        'constraint.eq_mismatch',
        '{path_prefix}值 {value} 不等于 {expected!r}',
        en='{path_prefix}value {value} does not equal {expected!r}',
    ),
    diagnostic_define('constraint.unique_only', '{path_prefix}unique 约束只适用于 list'),
    diagnostic_define('constraint.unique_dup', '{path_prefix}元素 {value} 重复'),
    diagnostic_define('constraint.has_only', '{path_prefix}has 约束只适用于 dict'),
    diagnostic_define('constraint.has_missing', '{path_prefix}缺少键 {key!r}'),
    diagnostic_define('constraint.field_only', '{path_prefix}field 约束只适用于 dict'),
    diagnostic_define('constraint.field_need', '{path_prefix}field() 的第二个参数必须是约束'),
    diagnostic_define('constraint.field_missing', '{path_prefix}字段 {field!r} 不存在'),
    diagnostic_define('constraint.not_need', '{path_prefix}not() 需要一个约束参数'),
    diagnostic_define('constraint.not_fail', '{path_prefix}not 约束失败（内部约束意外满足）'),
    diagnostic_define('constraint.any_fail', '{path_prefix}any 约束失败（所有子约束都不满足）'),
    diagnostic_define('constraint.one_none', '{path_prefix}one 约束失败（没有子约束被满足）'),
    diagnostic_define('constraint.one_many', '{path_prefix}one 约束失败（{count} 个子约束被满足: {names}）'),
    diagnostic_define('constraint.all_fail', '{path_prefix}all 约束失败'),
    diagnostic_define('constraint.when_need', '{path_prefix}when() 需要两个约束参数'),
    # ═══════════════════════════════════════════════════════════
    # 导入
    # ═══════════════════════════════════════════════════════════
    diagnostic_define('import.file_denied', '{path_prefix}文件导入超出沙盒授权，已忽略: {path_src}'),
    diagnostic_define('import.file_missing', '{path_prefix}导入文件不存在: {name}'),
    diagnostic_define('import.path_failed', '{path_prefix}无法解析导入路径: {name}'),
    diagnostic_define('import.template_denied', '{path_prefix}模板导入超出沙盒授权，已忽略: {path_src}'),
    diagnostic_define('import.yaml_missing', '{path_prefix}yaml 支持需要安装 PyYAML'),
    diagnostic_define('import.unsupported_format', '{path_prefix}不支持的文件格式: {format}'),
    diagnostic_define('import.parse_failed', '{path_prefix}解析数据失败: {error}'),
    diagnostic_define(
        'namespace.duplicate', '{path_prefix}导入别名 {name!r} 重复绑定（$ 命名空间内不允许重复），后者被拒绝'
    ),
)
