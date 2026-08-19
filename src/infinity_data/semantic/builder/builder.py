"""AST 构建器（Phase 2a）：RawAst + ResolvedContext → StdAst（携带约束，不执行）。

本层是纯数据变换：输入 :class:`Document`（语法产物）与 :class:`ResolvedContext`
（Phase 1 产物，数据模型），输出 :class:`StdDocument`。**不持有任何其他阶段对象**
（无 resolver / 无 executor / 无 registry / 无 schema）——子模块间仅经数据模型依赖。

值语义：字面量 / ``$`` 引用 / 模板展开 / dict 与 array 组装；
并把源文档约束解析为 :class:`ResolvedConstraint` 挂到节点（**不执行**）。
约束执行与顶层 schema 校验由 Phase 2b（:class:`~infinity_data.semantic.executor.ConstraintExecutor`）
在流水线中独立完成。

诊断写入调用方注入的共享 :class:`DiagnosticCollector`（流水线单一收集器），
本层不持有诊断列表、不产出诊断数据。
"""

from __future__ import annotations

import decimal
from collections.abc import Iterator
from typing import Any, cast

from infinity_data.infra.diagnostics import Diagnostic, DiagnosticCollector, Severity
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
from infinity_data.semantic.builder.models import (
    ResolvedConstraint,
    StdArray,
    StdDocument,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.semantic.constraints import resolve_constraint_list, resolve_constraints
from infinity_data.semantic.resolver.models import ResolvedContext, Scope, TemplateKey
from infinity_data.tokenizer.models.raw_tokens import SourceRange
from infinity_data.tokenizer.models.tokens import (
    BoolToken,
    FloatToken,
    IntegerToken,
    NoexistToken,
    NullToken,
    StringToken,
)

MAX_NESTING_DEPTH = 200
"""值嵌套深度上限，防止递归下降导致 RecursionError。"""


class AstBuilder:
    """AST 构建器（Phase 2a）：RawAst + ResolvedContext → StdAst（携带约束）。

    只做「值是什么」：字面量 / ``$`` 引用 / 模板展开 / dict 与 array 组装，
    并把源文档约束解析为 :class:`ResolvedConstraint` 挂到节点；
    **不执行任何约束**——校验由 Phase 2b 完成，本层与执行器零耦合。
    """

    def __init__(self) -> None:
        # 执行期状态（每次 build 重置）
        self._templates: dict[TemplateKey, TemplateDef] = {}
        self._template_scopes: dict[TemplateKey, Scope] = {}
        self._root_scope: Scope = {}
        self._schema_scope: Scope | None = None
        self._namespace: dict[str, Any] = {}  # $ 引用解析目标
        self._collector: DiagnosticCollector = DiagnosticCollector()  # 本次 build 的共享收集器
        self._depth = 0
        self._recursive_defaults: set[TemplateKey] = set()

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    def build(self, doc: Document, context: ResolvedContext, collector: DiagnosticCollector) -> StdDocument:
        """构建带约束的 StdAst（纯数据变换，不执行约束）。

        Args:
            doc: 语法分析产物
            context: Phase 1 产物（模板图 / 可见名表 / 命名空间，数据模型）
            collector: 共享诊断收集器（流水线单一收集器）

        Returns:
            :class:`StdDocument`——root 已构建、约束已挂载未执行；
            ``diagnostics`` 字段为空（诊断全部进 ``collector``，由流水线末端快照）。
        """
        self._templates = {}
        self._template_scopes = {}
        self._root_scope = {}
        self._schema_scope = None
        self._namespace = {}
        self._collector = collector
        self._depth = 0
        self._recursive_defaults = set()

        # Phase 1 产物注入执行期状态（按引用共享，约定只读）
        self._templates = context.templates
        self._template_scopes = context.template_scopes
        self._root_scope = context.root_scope
        self._schema_scope = context.schema_scope
        self._namespace = context.namespace

        # 静态防护：默认值引用环检测（默认值禁止自引用，见 neo_desg.md 2.6）
        self._detect_recursive_defaults()

        # 构建 root（顶层结构约束挂在 root.constraints，不执行）
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
                    self._collector.extend(diags)
                case _:
                    pass  # ErrorStatement 已在语法阶段诊断

        return StdDocument(
            root=StdObject(fields=root_fields, constraints=root_constraints),
            templates=dict(self._templates),
            scope=dict(self._root_scope),
        )

    # ═══════════════════════════════════════════════════════
    # 递归默认值防护（方案 C：默认引用图 + 静态环检测）
    # ═══════════════════════════════════════════════════════

    def _detect_recursive_defaults(self) -> None:
        """静态检测默认值引用环，标记禁展开模板并报告根因。

        模板实例化是原地展开；若某模板的默认值（经引用链）能回到自身，展开
        永不终止。只有**默认值**参与建图——调用方提供的值是新鲜的、有限的，
        不会引发无限展开。检测在展开前一次性完成，避免运行时白白展开
        ``MAX_NESTING_DEPTH`` 层再报错。
        """
        graph: dict[TemplateKey, set[TemplateKey]] = {}
        sources: dict[TemplateKey, dict[TemplateKey, SourceRange | None]] = {}

        for key, tpl in self._templates.items():
            scope = self._template_scopes.get(key, self._root_scope)
            refs: set[TemplateKey] = set()
            ref_src: dict[TemplateKey, SourceRange | None] = {}
            for tf in tpl.fields:
                for dep, src in self._iter_default_refs(tf.default_value, scope):
                    if dep not in refs:
                        refs.add(dep)
                        ref_src[dep] = src
            graph[key] = refs
            sources[key] = ref_src

        # DFS 三色标记找环：GRAY(1) 表示在当前展开栈上
        self._recursive_defaults = set()
        color: dict[TemplateKey, int] = {}
        stack: list[TemplateKey] = []

        def visit(key: TemplateKey) -> None:
            color[key] = 1
            stack.append(key)
            for dep in graph.get(key, ()):
                c = color.get(dep, 0)
                if c == 0:
                    visit(dep)
                elif c == 1:
                    start = stack.index(dep)
                    self._recursive_defaults.update(stack[start:])
            stack.pop()
            color[key] = 2

        for key in self._templates:
            if color.get(key, 0) == 0:
                visit(key)

        # 报告：定位到环上模板的默认值字段（根因），而非展开深处
        for key in self._recursive_defaults:
            src = next((s for dep, s in sources.get(key, {}).items() if dep in self._recursive_defaults), None)
            self._collector.add(
                Diagnostic(
                    Severity.ERROR,
                    'template.recursive_default',
                    {'template': key.name},
                    src,
                )
            )

    def _iter_default_refs(
        self,
        v: Value | None,
        scope: Scope,
    ) -> Iterator[tuple[TemplateKey, SourceRange | None]]:
        """遍历默认值 Value 树，产出其中的模板调用（真名, 调用位置）。"""
        if v is None:
            return
        match v:
            case TemplateCallValue(template_name=name, source=src):
                k = scope.get(name)
                if k is not None:
                    yield k, src
            case ArrayValue(elements=els):
                for e in els:
                    yield from self._iter_default_refs(e, scope)
            case DictValue(fields=fs):
                for f in fs:
                    yield from self._iter_default_refs(f.value, scope)
            case _:
                pass  # 字面量 / $ 引用 / 错误值不含模板调用

    # ═══════════════════════════════════════════════════════
    # 字段构建
    # ═══════════════════════════════════════════════════════

    def _build_field(self, field: Field, path: str, scope: Scope) -> StdField | None:
        """构建字段：解析值 + 解析注解约束（挂到节点，不执行）。"""
        value = self._resolve_value(field.value, path, scope)
        # 值缺失：设计文档未定义「裸 key」，noexist 需显式字面量
        if value is None:
            if not isinstance(field.value, ErrorValue):
                # 值解析失败已由语法层报告（parse.unrecognized_value 等），不重复报
                self._collector.add(Diagnostic(Severity.ERROR, 'field.missing_value', {}, field.source, path))
            return StdField(name=field.name, value=None, source=field.source)
        specs: list[ResolvedConstraint] = []
        if field.constraints is not None:
            specs, diags = resolve_constraints(field.constraints, scope)
            self._collector.extend(diags)
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
                self._collector.add(
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
                    self._collector.extend(diags)
                    return StdObject(fields=std_fields, constraints=specs)
                case ArrayValue(elements=els):
                    std_elements: list[StdValue] = []
                    for i, e in enumerate(els):
                        rv = self._resolve_value(e, f'{path}[{i}]', scope)
                        if rv is None:
                            continue
                        if isinstance(rv, StdLiteral) and rv.kind == 'noexist':
                            # noexist 仅用于 dict 字段；数组元素中无意义 → 报错并按 null 处理
                            self._collector.add(
                                Diagnostic(
                                    Severity.ERROR,
                                    'value.noexist_in_array',
                                    {},
                                    e.source,
                                    f'{path}[{i}]',
                                )
                            )
                            rv = StdLiteral(kind='null', value=None)
                        std_elements.append(rv)
                    return StdArray(elements=std_elements)
                case TemplateCallValue(
                    template_name=tn,
                    positional_args=pa,
                    named_args=na,
                ):
                    return self._expand_template_call(tn, pa, na, path, raw.source, scope)
                case ErrorValue():
                    # 值解析失败已在语法层报告（parse.value_field / parse.unrecognized_value），不重复
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
            self._collector.add(Diagnostic(Severity.WARNING, 'dollar.undefined', {'name': name}, path=path))
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
                    self._collector.add(
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
                    self._collector.add(
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
            self._collector.add(
                Diagnostic(Severity.ERROR, 'template.undefined', {'template': template_name}, source, path)
            )
            return StdObject()
        # 静态环检测已标记：默认值递归引用，禁止展开（根因错误已在定义处报告）
        if key in self._recursive_defaults:
            return StdObject()
        template = self._templates[key]
        inner_scope = self._template_scopes[key]

        required = [tf for tf in template.fields if tf.default_value is None]

        # 模板配置 positional=false：位置参数违规报错，但值仍绑定必填字段
        # （放宽必填绑定：只报 positional_disabled 一条，避免 missing_required 级联）
        if not template.config.positional and positional_args:
            self._collector.add(
                Diagnostic(
                    Severity.ERROR,
                    'template.positional_disabled',
                    {'template': template_name},
                    source,
                    path,
                )
            )

        # 未知命名参数 → ERROR（拒绝静默忽略）
        declared = {tf.name for tf in template.fields}
        for name in named_args:
            if name not in declared:
                self._collector.add(
                    Diagnostic(
                        Severity.ERROR,
                        'template.unknown_argument',
                        {'template': template_name, 'arg': name},
                        source,
                        path,
                    )
                )

        # 参数映射：位置参数按定义顺序绑定必填字段
        param_values: dict[str, Value] = dict(named_args)
        for idx, pos_val in enumerate(positional_args):
            if idx < len(required):
                rf = required[idx]
                if rf.name in param_values:
                    self._collector.add(
                        Diagnostic(
                            Severity.ERROR,
                            'template.arg_conflict',
                            {'template': template_name, 'field': rf.name},
                            source,
                            path,
                        )
                    )
                else:
                    param_values[rf.name] = pos_val
            else:
                self._collector.add(
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
                self._collector.add(
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
            self._collector.extend(diags)
            std_fields.append(StdField(name=tf.name, value=v, source=tf.source, constraints=specs))

        # 模板级约束（: 起始，约束整个 dict）：解析后挂到实例节点
        tpl_specs, tpl_diags = resolve_constraint_list(template.constraints, inner_scope)
        self._collector.extend(tpl_diags)
        return StdObject(fields=std_fields, template=key, constraints=tpl_specs)
