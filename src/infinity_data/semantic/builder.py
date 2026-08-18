"""AST 构建器（Phase 2a）：RawAst → StdAst（携带约束与展开值），不执行约束。

两阶段执行（对应 neo_desg.md）：

Phase 1（:mod:`infinity_data.semantic.resolver`，本模块不负责）：
  模板定义收集 / ``!from`` 模板导入 / ``!env``/``!file`` 数据导入
  → 产出不可变 :class:`ResolvedContext`（模板图 + 可见名表 + 命名空间）

Phase 2a（本模块 :class:`AstBuilder`）：
  值语义：字面量 / ``$`` 引用 / 模板展开 / dict 与 array 组装；
  并把源文档约束解析为 :class:`ResolvedConstraint` 挂到节点（**不执行**）

Phase 2b（:mod:`infinity_data.semantic.executor`）：
  :class:`ConstraintExecutor` 遍历 StdAst 执行约束 + 顶层 schema 校验

模板身份与可见性模型：
- 模板真名 :class:`TemplateKey`（来源文件内容 hash + 本地名），全局唯一
- 每个文件一张可见名表 scope（可见名 → 真名）；``!from ... import A as S``
  只把 ``S`` 映射进导入方 scope，原名不可见
- 名字解析（模板调用、约束里的模板名）在解析点经 scope 翻译成真名
"""

from __future__ import annotations

import decimal
from typing import Any, cast

from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.infra.file import File
from infinity_data.parser.models import (
    ArrayValue,
    ConstraintStmt,
    DictValue,
    Document,
    DollarValue,
    EnvImportStmt,
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
from infinity_data.semantic.constraints import resolve_constraint_list, resolve_constraints
from infinity_data.semantic.executor import ConstraintExecutor
from infinity_data.semantic.models import (
    ResolvedConstraint,
    ResolvedContext,
    Scope,
    StdArray,
    StdDocument,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
    TemplateKey,
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


class AstBuilder:
    """AST 构建器（Phase 2a）：RawAst → StdAst（携带约束与展开值）。

    只做「值是什么」：字面量 / ``$`` 引用 / 模板展开 / dict 与 array 组装，
    并把源文档约束解析为 :class:`ResolvedConstraint` 挂到节点；
    **不执行任何约束**——校验由 :class:`ConstraintExecutor`（Phase 2b）完成。

    显式依赖 :class:`TemplateGraphResolver`（Phase 1）：注册表与顶层 schema
    均从解析器共享获取，本层不自建任何 Phase 1 依赖。
    """

    def __init__(self, *, resolver: TemplateGraphResolver) -> None:
        self._resolver = resolver
        self._registry = resolver.registry
        self._schema = resolver.schema
        # 执行期状态（每次 analyze 重置）
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
        """构建带约束的 StdAst，并委托执行器完成约束校验。

        Phase 1（导入解析）委托给 :attr:`_resolver`，产出不可变上下文；
        本方法只做 Phase 2a（构建）并编排 Phase 2b（约束执行 + schema 校验）。

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
        self._adopt(context)

        # Phase 2a：构建 root（顶层结构约束挂在 root.constraints，不执行）
        root_fields: list[StdField] = []
        root_constraints: list[ResolvedConstraint] = []
        for stmt in doc.statements:
            match stmt:
                case TemplateDef() | TemplateImportStmt() | EnvImportStmt() | FileImportStmt():
                    continue  # 模板定义与导入不产生输出
                case Field():
                    f = self._build_field(stmt, path=stmt.name, scope=self._root_scope)
                    if f is not None:
                        root_fields.append(f)
                case ConstraintStmt(constraints=cs):
                    specs, diags = resolve_constraint_list(cs, self._root_scope)
                    root_constraints.extend(specs)
                    self._diagnostics.extend(diags)
                case _:
                    pass  # ErrorStatement 已在语法阶段诊断
        root = StdObject(fields=root_fields, constraints=root_constraints)

        # Phase 2b：约束执行（独立遍历器，工作在完成的 AST 上）
        executor = ConstraintExecutor(
            registry=self._registry,
            templates=self._templates,
            template_scopes=self._template_scopes,
        )
        self._diagnostics.extend(executor.validate(root))

        # 顶层 schema 校验（strict/lenient/strip）
        if self._schema is not None:
            scope = (
                self._schema_scope if self._schema.from_file and self._schema_scope is not None else self._root_scope
            )
            key = scope.get(self._schema.template)
            if key is None:
                raise SchemaError('schema.undefined_template', {'template': self._schema.template})
            tpl = self._templates[key]
            root, schema_diags = executor.apply_schema(root, self._schema, tpl, self._template_scopes[key])
            self._diagnostics.extend(schema_diags)

        diagnostics = sorted(self._diagnostics, key=lambda d: d.sort_key())
        return StdDocument(
            root=root,
            diagnostics=diagnostics,
            templates=dict(self._templates),
            scope=dict(self._root_scope),
        )

    def _adopt(self, context: ResolvedContext) -> None:
        """采纳 Phase 1 产物：模板图 / 可见名表 / 命名空间 / 诊断。"""
        self._templates = context.templates
        self._template_scopes = context.template_scopes
        self._root_scope = context.root_scope
        self._schema_scope = context.schema_scope
        self._namespace = context.namespace
        self._diagnostics = list(context.diagnostics)

    # ═══════════════════════════════════════════════════════
    # 字段构建
    # ═══════════════════════════════════════════════════════

    def _build_field(self, field: Field, path: str, scope: Scope) -> StdField | None:
        """构建字段：解析值 + 解析注解约束（挂到节点，不执行）。"""
        value = self._resolve_value(field.value, path, scope)
        # 值缺失：设计文档未定义「裸 key」，noexist 需显式字面量
        if value is None:
            self._diagnostics.append(Diagnostic(Severity.ERROR, 'field.missing_value', {}, field.source, path))
            return StdField(name=field.name, value=None, source=field.source)
        specs: list[ResolvedConstraint] = []
        if field.constraints is not None:
            specs, diags = resolve_constraints(field.constraints, scope)
            self._diagnostics.extend(diags)
        return StdField(name=field.name, value=value, source=field.source, constraints=specs)

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
                        sf = self._build_field(f, path=child, scope=scope)
                        if sf is not None:
                            std_fields.append(sf)
                    # dict 结构级约束（作用于该字面量整体）：解析后挂节点，不执行
                    specs, diags = resolve_constraint_list(cs, scope)
                    self._diagnostics.extend(diags)
                    return StdObject(fields=std_fields, constraints=specs)
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
        """展开模板调用为 StdObject（名字经调用点 scope 翻译，展开用模板定义点 scope）。

        字段 / 模板级约束解析后挂到节点（不执行），由执行器统一校验。
        """
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

            specs, diags = resolve_constraints(tf.constraints, inner_scope)
            self._diagnostics.extend(diags)
            std_fields.append(StdField(name=tf.name, value=v, source=tf.source, constraints=specs))

        # 模板级约束（: 起始，约束整个 dict）：解析后挂到实例节点
        tpl_specs, tpl_diags = resolve_constraint_list(template.constraints, inner_scope)
        self._diagnostics.extend(tpl_diags)
        return StdObject(fields=std_fields, template=key, constraints=tpl_specs)
