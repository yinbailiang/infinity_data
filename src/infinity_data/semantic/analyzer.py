"""语义分析器（Phase 2）：RawAst → StdAst，消费导入解析产物。

两阶段执行（对应 neo_desg.md）：

Phase 1（:mod:`infinity_data.semantic.resolver`，本模块不负责）：
  模板定义收集 / ``!from`` 模板导入 / ``!env``/``!file`` 数据导入
  → 产出不可变 :class:`ResolvedContext`（模板图 + 可见名表 + 命名空间）

Phase 2（本模块）：
  1. 模板名注册为同名校验器（**模板即约束**）
  2. 逐语句分析：模板展开、约束语法糖展开、约束链执行
  3. 顶层结构级约束校验（``: <...>``，作用于编译产物 root）
  4. 顶层 schema 校验（strict/lenient/strip）

模板身份与可见性模型：
- 模板真名 :class:`TemplateKey`（来源文件内容 hash + 本地名），全局唯一
- 每个文件一张可见名表 scope（可见名 → 真名）；``!from ... import A as S``
  只把 ``S`` 映射进导入方 scope，原名不可见
- 名字解析（模板调用、约束里的模板名）在解析点经 scope 翻译成真名
"""

from __future__ import annotations

import decimal
from collections.abc import Mapping
from typing import Any, cast

from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.infra.file import File
from infinity_data.parser.models import (
    ArrayValue,
    Constraint,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Constraints,
    ConstraintStmt,
    DictValue,
    Document,
    DollarValue,
    EnvImportStmt,
    ErrorConstraint,
    ErrorValue,
    Field,
    FileImportStmt,
    LiteralValue,
    TemplateCallValue,
    TemplateDef,
    TemplateImportStmt,
    Value,
)
from infinity_data.sandbox import SchemaError
from infinity_data.semantic.models import (
    Scope,
    StdArray,
    StdDocument,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
    TemplateKey,
)
from infinity_data.semantic.registry import (
    ConstraintFn,
    ConstraintResult,
    ResolvedConstraint,
    describe,
    fail_result,
    ok_result,
)
from infinity_data.semantic.resolver import TemplateGraphResolver
from infinity_data.tokenizer.models.raw_tokens import SourceRange
from infinity_data.tokenizer.models.tokens import (
    BoolToken,
    FloatToken,
    IntegerToken,
    MultilineStringToken,
    NoexistToken,
    NullToken,
    StringToken,
)

MAX_NESTING_DEPTH = 200
"""值嵌套深度上限，防止递归下降导致 RecursionError。"""

_INVALID_CONSTRAINT = '@invalid'


class SemanticAnalyzer:
    """语义分析器（Phase 2）：消费 :class:`ResolvedContext`，执行约束。

    显式依赖 :class:`TemplateGraphResolver`（Phase 1）：注册表与顶层 schema
    均从解析器共享获取，本层不自建任何 Phase 1 依赖（导入解析 / 沙盒 / 模板图）。
    """

    def __init__(self, *, resolver: TemplateGraphResolver) -> None:
        self._resolver = resolver
        self._registry = resolver.registry
        self._schema = resolver.schema
        # Phase 2 执行期状态（每次 analyze 重置）
        self._templates: dict[TemplateKey, TemplateDef] = {}
        self._template_scopes: dict[TemplateKey, Scope] = {}
        self._root_scope: Scope = {}
        self._schema_scope: Scope | None = None
        self._namespace: dict[str, Any] = {}  # $ 引用解析目标
        self._diagnostics: list[Diagnostic] = []
        self._depth = 0

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    def analyze(self, doc: Document, file: File) -> StdDocument:
        """主入口：分析 RawAst，返回 StandardAst。

        Phase 1（导入解析）委托给 :attr:`_resolver`，产出不可变上下文；
        本方法只做 Phase 2（模板即约束注册 + 逐语句分析 + schema 校验）。

        Args:
            doc: 语法分析产物
            file: 源码来源（诊断名 / 相对导入基准 / 内容 hash 均由它提供）
        """
        self._templates = {}
        self._template_scopes = {}
        self._root_scope = {}
        self._schema_scope = None
        self._namespace = {}
        self._diagnostics = []
        self._depth = 0

        # Phase 1：导入解析（独立对象，产出不可变上下文）
        context = self._resolver.resolve(doc, file)

        # Phase 1 产物注入执行期状态
        self._templates = context.templates
        self._template_scopes = context.template_scopes
        self._root_scope = context.root_scope
        self._schema_scope = context.schema_scope
        self._namespace = context.namespace
        self._diagnostics = list(context.diagnostics)

        # 模板名注册为约束（模板即约束，注册表键为真名字符串）
        for key, tpl in self._templates.items():
            self._registry.register(
                str(key),
                self._make_template_constraint(key, tpl),
                description=f'模板 {key.name} 结构约束',
            )

        # 第二遍：分析语句
        root_fields: list[StdField] = []
        root_constraints: list[Constraint] = []
        for stmt in doc.statements:
            match stmt:
                case TemplateDef() | TemplateImportStmt() | EnvImportStmt() | FileImportStmt():
                    continue  # 模板定义与导入不产生输出
                case Field():
                    f = self._analyze_field(stmt, path=stmt.name, scope=self._root_scope)
                    if f is not None:
                        root_fields.append(f)
                case ConstraintStmt(constraints=cs):
                    root_constraints.extend(cs)
                case _:
                    pass  # ErrorStatement 已在语法阶段诊断

        root = StdObject(fields=root_fields)

        # 顶层结构级约束（作用于编译产物 root）
        for c in root_constraints:
            result = self._execute_spec(self._resolve_constraint(c, self._root_scope), root, c.source, '')
            if not result.ok:
                self._diagnostics.extend(result.diagnostics)

        # 顶层 schema 约束（strict/lenient/strip）
        if self._schema is not None:
            root = self._apply_schema(root)

        diagnostics = sorted(self._diagnostics, key=lambda d: d.sort_key())
        return StdDocument(
            root=root,
            diagnostics=diagnostics,
            templates=dict(self._templates),
            scope=dict(self._root_scope),
        )

    # ═══════════════════════════════════════════════════════
    # 顶层 schema 约束
    # ═══════════════════════════════════════════════════════

    def _apply_schema(self, root: StdObject) -> StdObject:
        """对顶层对象执行 schema 模板约束（strict/lenient/strip）。"""
        assert self._schema is not None
        schema_scope = self._schema_scope
        scope = schema_scope if self._schema.from_file and schema_scope is not None else self._root_scope
        key = scope.get(self._schema.template)
        if key is None:
            raise SchemaError('schema.undefined_template', {'template': self._schema.template})
        tpl = self._templates[key]
        return self._check_schema_object(root, tpl, self._schema.mode, self._template_scopes[key])

    def _check_schema_object(self, obj: StdObject, tpl: TemplateDef, mode: str, scope: Scope) -> StdObject:
        """按模板校验顶层对象。失败抛 :class:`SchemaError`（strip 先过滤再校验）。"""
        declared = {tf.name for tf in tpl.fields}
        diags: list[Diagnostic] = []

        # 额外字段处理（模式差异）
        extra_names = [f.name for f in obj.fields if f.name not in declared]
        if extra_names:
            if mode == 'strict':
                diags.append(Diagnostic(Severity.ERROR, 'schema.extra_fields', {'fields': extra_names}, None))
            elif mode == 'lenient':
                self._diagnostics.append(
                    Diagnostic(Severity.WARNING, 'schema.extra_fields_lenient', {'fields': extra_names}, None)
                )
            else:  # strip
                obj = StdObject(fields=[f for f in obj.fields if f.name in declared], template=obj.template)

        # 必填字段缺失 → 报错
        for tf in tpl.fields:
            if tf.default_value is None and obj.get(tf.name) is None:
                diags.append(
                    Diagnostic(
                        Severity.ERROR,
                        'schema.missing_required',
                        {'field': tf.name, 'template': tpl.name},
                        None,
                        tf.name,
                    )
                )

        # 字段约束校验
        for tf in tpl.fields:
            f = obj.get(tf.name)
            if f is not None and f.value is not None:
                result = self._execute_constraints(tf.constraints, f.value, tf.source, tf.name, scope)
                if not result.ok:
                    diags.extend(result.diagnostics)

        # 模板级约束
        for c in tpl.constraints:
            result = self._execute_spec(self._resolve_constraint(c, scope), obj, None, '')
            if not result.ok:
                diags.extend(result.diagnostics)

        if diags:
            raise SchemaError('schema.failed', {'detail': '；'.join(d.message for d in diags)})
        return obj

    # ═══════════════════════════════════════════════════════
    # 模板即约束
    # ═══════════════════════════════════════════════════════

    def _make_template_constraint(self, key: TemplateKey, tpl: TemplateDef) -> ConstraintFn:
        """生成把模板当约束用的校验函数（校验手写 dict）。

        闭包捕获：模板 key（显示名用 key.name）、定义、allow_extra、声明字段集、
        以及模板所在文件的 scope（约束里的模板名按定义点可见性解析）。
        """
        allow_extra = self._resolve_config_bool(tpl, 'allow_extra')
        declared = {tf.name for tf in tpl.fields}
        display = key.name
        scope = self._template_scopes[key]

        def check(
            value: StdValue | None,
            source: SourceRange | None,
            path: str,
            args: list[Any],
            executor: Any,
        ) -> ConstraintResult:
            if value is None:
                return fail_result('template.expect_value', {'template': display}, source, path)
            if isinstance(value, StdLiteral):
                if value.kind == 'null':
                    return fail_result('template.null_use_nullable', {'template': display}, source, path)
                return fail_result(
                    'template.expect_object', {'template': display, 'actual': describe(value)}, source, path
                )
            if not isinstance(value, StdObject):
                return fail_result(
                    'template.expect_object', {'template': display, 'actual': describe(value)}, source, path
                )

            # 标记来源模板：这个手写 dict 被判定为模板 display 的结构（供下游引用）
            if value.template is None:
                value.template = key

            diags: list[Diagnostic] = []
            field_map = {f.name: f for f in value.fields}

            # 逐字段校验
            for tf in tpl.fields:
                child = f'{path}.{tf.name}' if path else tf.name
                f = field_map.get(tf.name)
                if f is None:
                    if tf.default_value is None:
                        diags.append(
                            Diagnostic(
                                Severity.ERROR,
                                'template.missing_field',
                                {'template': display, 'field': tf.name},
                                source,
                                child,
                            )
                        )
                    continue
                if f.value is not None:
                    result = self._execute_constraints(tf.constraints, f.value, tf.source, child, scope)
                    if not result.ok:
                        diags.extend(result.diagnostics)

            # 严格模式：不允许额外字段（allow_extra=true 时放行）
            if not allow_extra:
                for f in value.fields:
                    if f.name not in declared:
                        child = f'{path}.{f.name}' if path else f.name
                        diags.append(
                            Diagnostic(
                                Severity.ERROR,
                                'template.extra_field',
                                {'template': display, 'field': f.name},
                                f.source or source,
                                child,
                            )
                        )

            # 模板级约束
            for c in tpl.constraints:
                result = self._execute_spec(self._resolve_constraint(c, scope), value, source, path)
                if not result.ok:
                    diags.extend(result.diagnostics)

            if diags:
                return ConstraintResult(ok=False, diagnostics=diags)
            return ok_result()

        return check

    def _resolve_config_bool(self, tpl: TemplateDef, key: str) -> bool:
        """读取模板配置中的布尔项（如 allow_extra）。"""
        raw = tpl.config.get(key)
        match raw:
            case LiteralValue(value=BoolToken(value=b)):
                return b
            case _:
                return False

    # ═══════════════════════════════════════════════════════
    # 约束语法糖展开
    # ═══════════════════════════════════════════════════════

    def _expand_annotation(self, annotation: Constraints) -> Constraints:
        """展开约束语法糖：多约束 ``<a, b, c>`` → ``all(a, b, c)``。

        （``type?`` → ``one(type, ?)`` 已在 parser 阶段展开。）
        """
        if len(annotation.constraints) > 1:
            return Constraints(
                source=annotation.source,
                constraints=[
                    ConstraintCall(
                        source=annotation.source,
                        name='all',
                        arguments=list(annotation.constraints),
                    ),
                ],
            )
        return annotation

    # ═══════════════════════════════════════════════════════
    # 字段分析
    # ═══════════════════════════════════════════════════════

    def _analyze_field(self, field: Field, path: str, scope: Scope) -> StdField | None:
        """分析单个字段，返回 StdField。"""
        # 1. 解析值
        value = self._resolve_value(field.value, path, scope)

        # 2. 值缺失：设计文档未定义「裸 key」，noexist 需显式字面量
        if value is None:
            self._diagnostics.append(Diagnostic(Severity.ERROR, 'field.missing_value', {}, field.source, path))
            return StdField(name=field.name, value=None, source=field.source)

        # 3. 约束执行
        if field.constraints is not None:
            result = self._execute_constraints(field.constraints, value, field.source, path, scope)
            if not result.ok:
                self._diagnostics.extend(result.diagnostics)
            if result.coerced_value is not None:
                value = result.coerced_value

        return StdField(name=field.name, value=value, source=field.source)

    # ═══════════════════════════════════════════════════════
    # 值解析
    # ═══════════════════════════════════════════════════════

    def _resolve_value(self, raw: Value | None, path: str, scope: Scope) -> StdValue | None:
        """将 RawAst Value 转换为 StdValue。"""
        if raw is None:
            return None

        self._depth += 1
        try:
            if self._depth > MAX_NESTING_DEPTH:
                self._diagnostics.append(
                    Diagnostic(Severity.ERROR, 'value.nesting_depth', {'max': MAX_NESTING_DEPTH}, raw.source, path)
                )
                return None

            match raw:
                case LiteralValue(value=tok):
                    return self._convert_literal(tok)
                case DollarValue(name=n, type_cast=tc):
                    return self._resolve_dollar(n, tc, path)
                case DictValue(fields=fs, constraints=cs):
                    std_fields: list[StdField] = []
                    for f in fs:
                        child = f'{path}.{f.name}' if path else f.name
                        sf = self._analyze_field(f, path=child, scope=scope)
                        if sf is not None:
                            std_fields.append(sf)
                    obj = StdObject(fields=std_fields)
                    # dict 结构级约束（作用于该字面量整体）
                    for c in cs:
                        result = self._execute_spec(self._resolve_constraint(c, scope), obj, c.source, path)
                        if not result.ok:
                            self._diagnostics.extend(result.diagnostics)
                    return obj
                case ArrayValue(elements=els):
                    std_elements: list[StdValue] = []
                    for i, e in enumerate(els):
                        rv = self._resolve_value(e, f'{path}[{i}]', scope)
                        if rv is not None:
                            std_elements.append(rv)
                    return StdArray(elements=std_elements)
                case TemplateCallValue(
                    template_name=tn,
                    positional_args=pa,
                    named_args=na,
                ):
                    return self._expand_template_call(tn, pa, na, path, raw.source, scope)
                case ErrorValue(message=m):
                    self._diagnostics.append(
                        Diagnostic(Severity.ERROR, 'value.invalid', {'message': m}, raw.source, path)
                    )
                    return None
            return None
        finally:
            self._depth -= 1

    def _convert_literal(
        self,
        tok: StringToken | IntegerToken | FloatToken | BoolToken | NullToken | NoexistToken,
    ) -> StdLiteral:
        """将字面量 Token 转为 StdLiteral。"""
        match tok:
            case MultilineStringToken(value=v):
                return StdLiteral(kind='str', value=v)
            case StringToken(value=v):
                return StdLiteral(kind='str', value=v)
            case IntegerToken(value=v):
                return StdLiteral(kind='int', value=v)
            case FloatToken(value=v):
                return StdLiteral(kind='float', value=v)  # Decimal，含 NaN/±Inf
            case BoolToken(value=v):
                return StdLiteral(kind='bool', value=v)
            case NullToken():
                return StdLiteral(kind='null', value=None)
            case NoexistToken():
                return StdLiteral(kind='noexist', value=None)
        raise TypeError(f'未知字面量 token 类型: {type(tok)}')

    def _resolve_dollar(self, name: str, type_cast: str | None, path: str) -> StdValue:
        """解析 ``$name`` 引用，type_cast 为显式 as bool/int/float/str 转换。"""
        if name not in self._namespace:
            self._diagnostics.append(Diagnostic(Severity.WARNING, 'dollar.undefined', {'name': name}, path=path))
            return StdLiteral(kind='null', value=None)

        raw = self._namespace[name]
        if type_cast is None:
            return self._auto_literal(raw)

        match type_cast:
            case 'bool':
                if isinstance(raw, bool):
                    val: bool = raw
                elif isinstance(raw, str):
                    val = raw.lower() in ('true', '1')
                elif isinstance(raw, int | float):
                    val = bool(raw)
                else:
                    val = False
                return StdLiteral(kind='bool', value=val)
            case 'int':
                try:
                    return StdLiteral(kind='int', value=int(raw))
                except (ValueError, TypeError):
                    self._diagnostics.append(
                        Diagnostic(
                            Severity.WARNING,
                            'dollar.convert_failed',
                            {'name': name, 'raw': raw, 'type': 'int'},
                            path=path,
                        )
                    )
                    return StdLiteral(kind='int', value=0)
            case 'float':
                try:
                    return StdLiteral(kind='float', value=decimal.Decimal(str(raw)))
                except (ValueError, TypeError, decimal.InvalidOperation):
                    self._diagnostics.append(
                        Diagnostic(
                            Severity.WARNING,
                            'dollar.convert_failed',
                            {'name': name, 'raw': raw, 'type': 'float'},
                            path=path,
                        )
                    )
                    return StdLiteral(kind='float', value=decimal.Decimal(0))
            case 'str':
                return StdLiteral(kind='str', value=str(raw))
            case _:
                return self._auto_literal(raw)

    def _auto_literal(self, raw: Any) -> StdValue:
        """根据 Python 类型自动推断 StdValue（导入数据）。"""
        if raw is None:
            return StdLiteral(kind='null', value=None)
        if isinstance(raw, bool):
            return StdLiteral(kind='bool', value=raw)
        if isinstance(raw, int):
            return StdLiteral(kind='int', value=raw)
        if isinstance(raw, decimal.Decimal):
            return StdLiteral(kind='float', value=raw)
        if isinstance(raw, float):
            return StdLiteral(kind='float', value=decimal.Decimal(str(raw)))
        if isinstance(raw, str):
            return StdLiteral(kind='str', value=raw)
        if isinstance(raw, list):
            items = cast(list[Any], raw)
            return StdArray(elements=[self._auto_literal(e) for e in items])
        if isinstance(raw, dict):
            mapping = cast(dict[Any, Any], raw)
            return StdObject(fields=[StdField(name=str(k), value=self._auto_literal(v)) for k, v in mapping.items()])
        return StdLiteral(kind='str', value=str(raw))

    # ═══════════════════════════════════════════════════════
    # 模板展开
    # ═══════════════════════════════════════════════════════

    def _expand_template_call(
        self,
        template_name: str,
        positional_args: list[Value],
        named_args: dict[str, Value],
        path: str,
        source: SourceRange | None,
        scope: Scope,
    ) -> StdValue:
        """展开模板调用为 StdObject（名字经调用点 scope 翻译，展开用模板定义点 scope）。"""
        key = scope.get(template_name)
        if key is None:
            self._diagnostics.append(
                Diagnostic(Severity.ERROR, 'template.undefined', {'template': template_name}, source, path)
            )
            return StdObject()
        template = self._templates[key]
        inner_scope = self._template_scopes[key]

        required = [tf for tf in template.fields if tf.default_value is None]

        # 参数映射：位置参数按定义顺序绑定必填字段
        param_values: dict[str, Value] = dict(named_args)
        for idx, pos_val in enumerate(positional_args):
            if idx < len(required):
                rf = required[idx]
                if rf.name in param_values:
                    self._diagnostics.append(
                        Diagnostic(
                            Severity.WARNING,
                            'template.arg_conflict',
                            {'template': template_name, 'field': rf.name},
                            source,
                            path,
                        )
                    )
                else:
                    param_values[rf.name] = pos_val
            else:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        'template.too_many_positional',
                        {'template': template_name, 'count': len(required), 'given': len(positional_args)},
                        source,
                        path,
                    )
                )

        # 必填字段缺失检查
        for rf in required:
            if rf.name not in param_values:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        'template.missing_required',
                        {'template': template_name, 'field': rf.name},
                        source,
                        path,
                    )
                )

        # 展开所有字段（参数覆盖 > 默认值 > 缺失）
        # 参数值按调用点 scope 解析；默认值按模板定义点 scope（inner_scope）解析
        std_fields: list[StdField] = []
        for tf in template.fields:
            child = f'{path}.{tf.name}' if path else tf.name

            if tf.name in param_values:
                v = self._resolve_value(param_values[tf.name], child, scope)
            elif tf.default_value is not None:
                v = self._resolve_value(tf.default_value, child, inner_scope)
            else:
                continue  # 必填且未提供 → 已在上面报错

            if v is not None:
                result = self._execute_constraints(tf.constraints, v, tf.source, child, inner_scope)
                if not result.ok:
                    self._diagnostics.extend(result.diagnostics)
                if result.coerced_value is not None:
                    v = result.coerced_value
            std_fields.append(StdField(name=tf.name, value=v, source=tf.source))

        obj = StdObject(fields=std_fields, template=key)

        # 模板级约束（: 起始，约束整个 dict）
        for c in template.constraints:
            result = self._execute_spec(self._resolve_constraint(c, inner_scope), obj, source, path)
            if not result.ok:
                self._diagnostics.extend(result.diagnostics)

        return obj

    # ═══════════════════════════════════════════════════════
    # 约束执行
    # ═══════════════════════════════════════════════════════

    def _execute_constraints(
        self,
        annotation: Constraints,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
        scope: Scope,
    ) -> ConstraintResult:
        """对值依次执行约束链（语法糖展开 → 逐约束执行 → 值强制转换）。"""
        expanded = self._expand_annotation(annotation)
        current = value
        for c in expanded.constraints:
            result = self._execute_spec(self._resolve_constraint(c, scope), current, source, path)
            if not result.ok:
                return result  # 一个失败即短路
            if result.coerced_value is not None:
                current = result.coerced_value
        return ConstraintResult(ok=True, coerced_value=current)

    def _execute_spec(
        self,
        spec: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult:
        """执行已解析的约束规格。

        诊断位置优先取约束自身的 source（spec.source，精确到该约束表达式），
        无约束位置时回退到外层 source（字段/注释点）。
        """
        if spec.name == _INVALID_CONSTRAINT:
            return fail_result('constraint.invalid', {}, source, path)
        return self._registry.apply(spec, value, spec.source or source, path, self._apply_nested)

    def _apply_nested(
        self,
        constraint: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult:
        """嵌套约束执行回调（Executor 协议）。

        与 :meth:`_execute_spec` 一致：优先用嵌套约束自身的位置寻址。
        """
        return self._registry.apply(constraint, value, constraint.source or source, path, self._apply_nested)

    def _resolve_constraint(self, c: Constraint, scope: Scope) -> ResolvedConstraint:
        """解析约束 AST 为约束规格（名字经 scope 翻译为真名）。"""
        match c:
            case ConstraintIdent(name=n):
                return ResolvedConstraint(name=self._translate_name(n, scope), source=c.source)
            case ConstraintCall(name=n, arguments=args):
                return ResolvedConstraint(
                    name=self._translate_name(n, scope),
                    args=[self._resolve_constraint_arg(a, scope) for a in args],
                    source=c.source,
                )
            case ConstraintLiteral():
                return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source)
            case ErrorConstraint(message=m):
                self._diagnostics.append(Diagnostic(Severity.ERROR, 'error.generic', {'message': m}, c.source))
                return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source)
        return ResolvedConstraint(name=_INVALID_CONSTRAINT)

    def _resolve_constraint_arg(self, c: Constraint, scope: Scope) -> Any:
        """解析约束参数：嵌套约束 → ResolvedConstraint；字面量 → Python 值。"""
        match c:
            case ConstraintIdent(name=n):
                return ResolvedConstraint(name=self._translate_name(n, scope), source=c.source)
            case ConstraintCall(name=n, arguments=args):
                return ResolvedConstraint(
                    name=self._translate_name(n, scope),
                    args=[self._resolve_constraint_arg(a, scope) for a in args],
                    source=c.source,
                )
            case ConstraintLiteral(value=lit):
                return self._literal_python_value(lit)
            case ErrorConstraint(message=m):
                self._diagnostics.append(Diagnostic(Severity.ERROR, 'error.generic', {'message': m}, c.source))
                return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source)
        return ResolvedConstraint(name=_INVALID_CONSTRAINT)

    @staticmethod
    def _translate_name(name: str, scope: Scope) -> str:
        """可见名 → 真名字符串。未命中（如 has(field) 的裸字段名）保留原名。"""
        key = scope.get(name)
        return str(key) if key is not None else name

    @staticmethod
    def _literal_python_value(lit: LiteralValue) -> Any:
        """约束参数字面量 → Python 值。"""
        match lit.value:
            case IntegerToken(value=v):
                return v
            case FloatToken(value=v):
                return v
            case BoolToken(value=v):
                return v
            case MultilineStringToken(value=v):
                return v
            case StringToken(value=v):
                return v
            case NullToken():
                return None
            case NoexistToken():
                return None
        return None

    # ═══════════════════════════════════════════════════════
    # 诊断辅助
    # ═══════════════════════════════════════════════════════

    def _report(self, severity: Severity, code: str, params: Mapping[str, Any], source: SourceRange | None) -> None:
        self._diagnostics.append(Diagnostic(severity=severity, code=code, params=dict(params), source=source))
