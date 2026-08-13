"""语义分析器：RawAst → StdAst。

执行顺序（对应 neo_desg.md）：

1. 收集模板定义（重复定义警告、必填字段排序校验）
2. 解析导入语句（``!env`` / ``!file`` / ``!from``）
3. 模板名注册为同名校验器（**模板即约束**）
4. 逐语句分析：模板展开、约束语法糖展开、约束链执行
"""

from __future__ import annotations

import decimal
from typing import Any, cast

from infinity_data.parser.models import (
    ArrayValue,
    Constraint,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Constraints,
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
from infinity_data.semantic.imports import ImportResolver
from infinity_data.semantic.models import (
    Diagnostic,
    Severity,
    StdArray,
    StdDocument,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.semantic.registry import (
    ConstraintFn,
    ConstraintRegistry,
    ConstraintResult,
    ResolvedConstraint,
    describe,
    fail_result,
    ok_result,
)
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
    """语义分析器：将 RawAst 转换为 StandardAst。"""

    def __init__(
        self,
        *,
        registry: ConstraintRegistry | None = None,
        import_resolver: ImportResolver | None = None,
    ) -> None:
        self._registry = registry or ConstraintRegistry()
        self._imports = import_resolver or ImportResolver()
        self._templates: dict[str, TemplateDef] = {}
        self._namespace: dict[str, Any] = {}  # $ 引用解析目标
        self._diagnostics: list[Diagnostic] = []
        self._depth = 0

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    def analyze(self, doc: Document) -> StdDocument:
        """主入口：分析 RawAst，返回 StandardAst。"""
        self._templates = {}
        self._namespace = {}
        self._diagnostics = []
        self._depth = 0

        # 第一遍：收集模板定义
        self._collect_templates(doc)

        # 解析导入语句
        self._namespace = self._imports.resolve(doc, self._report)

        # 模板名注册为约束（模板即约束）
        for name, tpl in self._templates.items():
            self._registry.register(
                name,
                self._make_template_constraint(name, tpl),
                description=f'模板 {name} 结构约束',
            )

        # 第二遍：分析语句
        root_fields: list[StdField] = []
        for stmt in doc.statements:
            match stmt:
                case TemplateDef() | TemplateImportStmt() | EnvImportStmt() | FileImportStmt():
                    continue  # 模板定义与导入不产生输出
                case Field():
                    f = self._analyze_field(stmt, path=stmt.name)
                    if f is not None:
                        root_fields.append(f)
                case _:
                    pass  # ErrorStatement 已在语法阶段诊断

        diagnostics = sorted(self._diagnostics, key=lambda d: d.sort_key())
        return StdDocument(root=StdObject(fields=root_fields), diagnostics=diagnostics)

    # ═══════════════════════════════════════════════════════
    # 模板收集
    # ═══════════════════════════════════════════════════════

    def _collect_templates(self, doc: Document) -> None:
        for stmt in doc.statements:
            if not isinstance(stmt, TemplateDef):
                continue
            if stmt.name in self._templates:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        f'模板 {stmt.name!r} 重复定义，后者覆盖前者',
                        stmt.source,
                    )
                )
            # 必填字段必须全部在可选字段之前
            seen_optional = False
            for tf in stmt.fields:
                if tf.default_value is None:
                    if seen_optional:
                        self._diagnostics.append(
                            Diagnostic(
                                Severity.ERROR,
                                f'模板 {stmt.name!r} 中必填字段 {tf.name!r} 出现在可选字段之后',
                                tf.source,
                            )
                        )
                else:
                    seen_optional = True
            self._templates[stmt.name] = stmt

    # ═══════════════════════════════════════════════════════
    # 模板即约束
    # ═══════════════════════════════════════════════════════

    def _make_template_constraint(self, name: str, tpl: TemplateDef) -> ConstraintFn:
        """生成把模板当约束用的校验函数（校验手写 dict）。"""
        allow_extra = self._resolve_config_bool(tpl, 'allow_extra')
        declared = {tf.name for tf in tpl.fields}

        def check(
            value: StdValue | None,
            source: SourceRange | None,
            path: str,
            args: list[Any],
            executor: Any,
        ) -> ConstraintResult:
            if value is None:
                return fail_result(f'{path}: 期望 {name}（模板约束），实际没有值', source, path)
            if isinstance(value, StdLiteral):
                if value.kind == 'null':
                    return fail_result(
                        f'{path}: 期望 {name}，实际 null（使用 {name}? 允许可空）',
                        source,
                        path,
                    )
                return fail_result(f'{path}: 期望 {name}（对象），实际 {describe(value)}', source, path)
            if not isinstance(value, StdObject):
                return fail_result(f'{path}: 期望 {name}（对象），实际 {describe(value)}', source, path)

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
                                f'{child}: 模板 {name} 的必填字段 {tf.name!r} 缺失',
                                source,
                                child,
                            )
                        )
                    continue
                if f.value is not None:
                    result = self._execute_constraints(tf.constraints, f.value, tf.source, child)
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
                                f'{child}: 模板 {name} 不允许额外字段 {f.name!r}',
                                f.source or source,
                                child,
                            )
                        )

            # 模板级约束
            for c in tpl.constraints:
                result = self._execute_spec(self._resolve_constraint(c), value, source, path)
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

    def _analyze_field(self, field: Field, path: str) -> StdField | None:
        """分析单个字段，返回 StdField。"""
        # 1. 解析值
        value = self._resolve_value(field.value, path)

        # 2. 值缺失：设计文档未定义「裸 key」，noexist 需显式字面量
        if value is None:
            self._diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f'{path}: 字段缺少值（如需 noexist 请显式书写 = noexist）',
                    field.source,
                )
            )
            return StdField(name=field.name, value=None, source=field.source)

        # 3. 约束执行
        if field.constraints is not None:
            result = self._execute_constraints(field.constraints, value, field.source, path)
            if not result.ok:
                self._diagnostics.extend(result.diagnostics)
            if result.coerced_value is not None:
                value = result.coerced_value

        return StdField(name=field.name, value=value, source=field.source)

    # ═══════════════════════════════════════════════════════
    # 值解析
    # ═══════════════════════════════════════════════════════

    def _resolve_value(self, raw: Value | None, path: str) -> StdValue | None:
        """将 RawAst Value 转换为 StdValue。"""
        if raw is None:
            return None

        self._depth += 1
        try:
            if self._depth > MAX_NESTING_DEPTH:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f'{path}: 嵌套层级超过上限 {MAX_NESTING_DEPTH}',
                        raw.source,
                    )
                )
                return None

            match raw:
                case LiteralValue(value=tok):
                    return self._convert_literal(tok)
                case DollarValue(name=n, type_cast=tc):
                    return self._resolve_dollar(n, tc, path)
                case DictValue(fields=fs):
                    std_fields: list[StdField] = []
                    for f in fs:
                        child = f'{path}.{f.name}' if path else f.name
                        sf = self._analyze_field(f, path=child)
                        if sf is not None:
                            std_fields.append(sf)
                    return StdObject(fields=std_fields)
                case ArrayValue(elements=els):
                    std_elements: list[StdValue] = []
                    for i, e in enumerate(els):
                        rv = self._resolve_value(e, f'{path}[{i}]')
                        if rv is not None:
                            std_elements.append(rv)
                    return StdArray(elements=std_elements)
                case TemplateCallValue(
                    template_name=tn,
                    positional_args=pa,
                    named_args=na,
                ):
                    return self._expand_template_call(tn, pa, na, path, raw.source)
                case ErrorValue(message=m):
                    self._diagnostics.append(Diagnostic(Severity.ERROR, f'{path}: {m}', raw.source))
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
            self._diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    f'{path}: 未找到导入变量 ${name}',
                )
            )
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
                            f'{path}: 无法将 ${name}={raw!r} 转为 int',
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
                            f'{path}: 无法将 ${name}={raw!r} 转为 float',
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
            return StdObject(fields=[
                StdField(name=str(k), value=self._auto_literal(v))
                for k, v in mapping.items()
            ])
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
    ) -> StdValue:
        """展开模板调用为 StdObject。"""
        template = self._templates.get(template_name)
        if template is None:
            self._diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f'{path}: 未定义的模板 {template_name!r}',
                    source,
                )
            )
            return StdObject()

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
                            f'{path}: 模板 {template_name!r} 字段 {rf.name!r} 同时以位置和命名参数提供',
                            source,
                        )
                    )
                else:
                    param_values[rf.name] = pos_val
            else:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        f'{path}: 模板 {template_name!r} 只有 {len(required)} 个必填字段，'
                        f'提供了 {len(positional_args)} 个位置参数',
                        source,
                    )
                )

        # 必填字段缺失检查
        for rf in required:
            if rf.name not in param_values:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f'{path}: 模板 {template_name!r} 的必填字段 {rf.name!r} 未提供',
                        source,
                    )
                )

        # 展开所有字段（参数覆盖 > 默认值 > 缺失）
        std_fields: list[StdField] = []
        for tf in template.fields:
            child = f'{path}.{tf.name}' if path else tf.name

            if tf.name in param_values:
                v = self._resolve_value(param_values[tf.name], child)
            elif tf.default_value is not None:
                v = self._resolve_value(tf.default_value, child)
            else:
                continue  # 必填且未提供 → 已在上面报错

            if v is not None:
                result = self._execute_constraints(tf.constraints, v, tf.source, child)
                if not result.ok:
                    self._diagnostics.extend(result.diagnostics)
                if result.coerced_value is not None:
                    v = result.coerced_value
            std_fields.append(StdField(name=tf.name, value=v, source=tf.source))

        obj = StdObject(fields=std_fields)

        # 模板级约束（: 起始，约束整个 dict）
        for c in template.constraints:
            result = self._execute_spec(self._resolve_constraint(c), obj, source, path)
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
    ) -> ConstraintResult:
        """对值依次执行约束链（语法糖展开 → 逐约束执行 → 值强制转换）。"""
        expanded = self._expand_annotation(annotation)
        current = value
        for c in expanded.constraints:
            result = self._execute_spec(self._resolve_constraint(c), current, source, path)
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
        """执行已解析的约束规格。"""
        if spec.name == _INVALID_CONSTRAINT:
            return fail_result(f'{path}: 无效的约束表达式', source, path)
        return self._registry.apply(spec, value, source, path, self._apply_nested)

    def _apply_nested(
        self,
        constraint: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult:
        """嵌套约束执行回调（Executor 协议）。"""
        return self._registry.apply(constraint, value, source, path, self._apply_nested)

    def _resolve_constraint(self, c: Constraint) -> ResolvedConstraint:
        """解析约束 AST 为约束规格（顶层位置）。"""
        match c:
            case ConstraintIdent(name=n):
                return ResolvedConstraint(name=n, source=c.source)
            case ConstraintCall(name=n, arguments=args):
                return ResolvedConstraint(
                    name=n,
                    args=[self._resolve_constraint_arg(a) for a in args],
                    source=c.source,
                )
            case ConstraintLiteral():
                return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source)
            case ErrorConstraint(message=m):
                self._diagnostics.append(Diagnostic(Severity.ERROR, m, c.source))
                return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source)
        return ResolvedConstraint(name=_INVALID_CONSTRAINT)

    def _resolve_constraint_arg(self, c: Constraint) -> Any:
        """解析约束参数：嵌套约束 → ResolvedConstraint；字面量 → Python 值。"""
        match c:
            case ConstraintIdent(name=n):
                return ResolvedConstraint(name=n, source=c.source)
            case ConstraintCall(name=n, arguments=args):
                return ResolvedConstraint(
                    name=n,
                    args=[self._resolve_constraint_arg(a) for a in args],
                    source=c.source,
                )
            case ConstraintLiteral(value=lit):
                return self._literal_python_value(lit)
            case ErrorConstraint(message=m):
                self._diagnostics.append(Diagnostic(Severity.ERROR, m, c.source))
                return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source)
        return ResolvedConstraint(name=_INVALID_CONSTRAINT)

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

    def _report(self, severity: Severity, message: str, source: SourceRange | None) -> None:
        self._diagnostics.append(Diagnostic(severity=severity, message=message, source=source))
