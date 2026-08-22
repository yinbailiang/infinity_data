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
from infinity_data.parser import (
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
    UnpackValue,
    Value,
    VarStmt,
    walk,
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
from infinity_data.semantic.jsonpath import apply_json_path
from infinity_data.semantic.resolver.models import ResolvedContext, Scope, TemplateKey
from infinity_data.semantic.std import STD_VALUE_TYPES
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
        self._namespace: dict[str, StdValue] = {}  # $ 引用解析目标（!env/!file/!var 统一为 StdValue）
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

        # 模板配置校验：extra_*_vars 指向的字段必须在模板中声明（§2.9，定义即报错）
        self._check_variadic_config()

        # !var 求值（§2.10）：root 构建前填充 $ 命名空间（前向引用 + 环检测）
        self._resolve_var_statements(doc)

        # 构建 root（顶层结构约束挂在 root.constraints，不执行）
        root_fields: list[StdField] = []
        root_constraints: list[ResolvedConstraint] = []
        for stmt in doc.statements:
            match stmt:
                case TemplateDef() | TemplateImportStmt() | EnvImportStmt() | FileImportStmt():
                    continue  # 模板定义与导入不产生输出
                case UnpackValue(value=uv, double=d):
                    # 顶层（隐式 dict）**expr 解包：展开为顶层字段（disjoint merge 查重）
                    if not d:
                        self._err('unpack.type_error', {'want': 'dict'}, stmt.source, '')
                        continue
                    rv = self._resolve_value(uv, '', self._root_scope)
                    fields = self._unpack_dict(rv, stmt.source, '')
                    if fields is not None:
                        root_fields.extend(fields)
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
            root=StdObject(fields=self._finalize_object(root_fields, ''), constraints=root_constraints),
            templates=dict(self._templates),
            scope=dict(self._root_scope),
        )

    # ═══════════════════════════════════════════════════════
    # !var 求值（§2.10）
    # ═══════════════════════════════════════════════════════

    def _resolve_var_statements(self, doc: Document) -> None:
        """!var 求值：静态依赖图 + 环检测 + 拓扑求值 + path 投影，填充 $ 命名空间。

        在 root 构建之前调用——前向引用经拓扑序天然支持；依赖环 → ``var.cycle``。
        值构造（模板展开 / 解包 / $ 引用）全部复用 :meth:`_resolve_value`。
        """
        stmts = [s for s in doc.statements if isinstance(s, VarStmt)]
        if not stmts:
            return
        by_alias = {s.alias: i for i, s in enumerate(stmts)}

        # 1) 依赖图：!var 的 $ 引用指向其他 !var 别名 → 边（walk 静态提取）
        deps: dict[int, set[int]] = {}
        for i, s in enumerate(stmts):
            dep_indices: set[int] = set()
            for node in walk(s):
                if isinstance(node, DollarValue) and node.name in by_alias:
                    dep_indices.add(by_alias[node.name])
            deps[i] = dep_indices

        # 2) DFS 环检测 + 拓扑序（依赖在前；环上节点报错但继续，容错）
        visited: set[int] = set()
        on_stack: set[int] = set()
        order: list[int] = []

        def visit(i: int) -> None:
            if i in visited:
                return
            if i in on_stack:
                self._err('var.cycle', {'alias': stmts[i].alias}, stmts[i].source, '')
                return
            on_stack.add(i)
            for d in deps[i]:
                visit(d)
            on_stack.remove(i)
            visited.add(i)
            order.append(i)

        for i in range(len(stmts)):
            visit(i)

        # 3) 拓扑序求值 → path 投影 → 填 namespace（duplicate 检测）
        for i in order:
            s = stmts[i]
            rv = self._resolve_value(s.value, '', self._root_scope)
            if rv is None:
                continue  # 值解析失败已报告
            if s.json_path:
                try:
                    rv = apply_json_path(rv, s.json_path)
                except (KeyError, IndexError, TypeError):
                    self._err('var.path_failed', {'alias': s.alias}, s.source, '')
                    continue
            if s.alias in self._namespace:
                self._err('namespace.duplicate', {'name': s.alias}, s.source, '')
                continue
            self._namespace[s.alias] = rv

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
        v: Value | UnpackValue | None,
        scope: Scope,
    ) -> Iterator[tuple[TemplateKey, SourceRange | None]]:
        """遍历默认值 Value 树，产出其中的模板调用（真名, 调用位置）。

        基于 :func:`walk`（节点自带 ``children``）统一遍历。
        """
        if v is None:
            return
        for node in walk(v):
            if isinstance(node, TemplateCallValue):
                k = scope.get(node.template_name)
                if k is not None:
                    yield k, node.source

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
                self._err('field.missing_value', {}, field.source, path)
            return StdField(name=field.name, value=None, source=field.source)
        specs: list[ResolvedConstraint] = []
        if field.constraints is not None:
            specs, diags = resolve_constraints(field.constraints, scope)
            self._collector.extend(diags)
        return StdField(name=field.name, value=value, source=field.source, constraints=specs)

    def _finalize_object(self, fields: list[StdField], path: str) -> list[StdField]:
        """同一 dict 内同名键 → 错误（dict.duplicate_key），保留先到者。

        手写字段 / 解包合并 / 模板展开产出的字段统一在此查重——「零静默覆盖」：
        重复键一律报错，最终键集 = 先到者（§1.1 / §2.7 disjoint merge）。
        """
        if len(fields) <= 1:
            return fields
        seen: set[str] = set()
        result: list[StdField] = []
        for f in fields:
            if f.name in seen:
                self._err('dict.duplicate_key', {'name': f.name}, f.source, f'{path}.{f.name}' if path else f.name)
            else:
                seen.add(f.name)
                result.append(f)
        return result

    # ═══════════════════════════════════════════════════════
    # 模板配置校验（§2.9 可变参数收集）
    # ═══════════════════════════════════════════════════════

    def _check_variadic_config(self) -> None:
        """模板配置校验：extra_*_vars 指向的字段必须在模板中声明（定义即报错）。

        覆盖本地 + ``!from`` 导入的全部模板（self._templates）。
        """
        for tpl in self._templates.values():
            declared = {tf.name for tf in tpl.fields}
            for cfg_field in (tpl.config.extra_positional_vars, tpl.config.extra_named_vars):
                if cfg_field is not None and cfg_field not in declared:
                    self._err(
                        'template.variadic_target_missing',
                        {'template': tpl.name, 'field': cfg_field},
                        tpl.source,
                        '',
                    )
            if tpl.config.extra_positional_vars is not None and not tpl.config.positional:
                self._err(
                    'template.variadic_positional_conflict',
                    {'template': tpl.name},
                    tpl.source,
                    '',
                )

    # ═══════════════════════════════════════════════════════
    # 诊断 / 解包辅助（消除重复构造）
    # ═══════════════════════════════════════════════════════

    def _err(self, code: str, params: dict[str, Any], source: SourceRange | None, path: str) -> None:
        """ERROR 诊断快捷构造（写入共享收集器）。"""
        self._collector.add(Diagnostic(Severity.ERROR, code, params, source, path))

    def _warn(self, code: str, params: dict[str, Any], source: SourceRange | None, path: str) -> None:
        """WARNING 诊断快捷构造（写入共享收集器）。"""
        self._collector.add(Diagnostic(Severity.WARNING, code, params, source, path))

    def _unpack_dict(self, rv: StdValue | None, source: SourceRange | None, path: str) -> list[StdField] | None:
        """** 解包目标检查 + 展开：rv 为 dict → 返回其字段；None/非 dict → 报错返回 None。"""
        if isinstance(rv, StdObject):
            return rv.fields
        if rv is None:
            return None  # 值解析失败已报告
        self._err('unpack.type_error', {'want': 'dict'}, source, path)
        return None

    def _unpack_list(self, rv: StdValue | None, source: SourceRange | None, path: str) -> list[StdValue] | None:
        """* 解包目标检查 + 展开（含数组 noexist 处理）；None/非 list → 报错返回 None。"""
        if isinstance(rv, StdArray):
            return [self._array_noexist(e, source, path) for e in rv.elements]
        if rv is None:
            return None
        self._err('unpack.type_error', {'want': 'list'}, source, path)
        return None

    def _array_noexist(self, value: StdValue, source: SourceRange | None, path: str) -> StdValue:
        """数组元素 noexist → 报错并按 null（保留位置）。"""
        if isinstance(value, StdLiteral) and value.kind == 'noexist':
            self._err('value.noexist_in_array', {}, source, path)
            return StdLiteral(kind='null', value=None)
        return value

    def _bind_to_std(self, value: Value | StdValue, path: str, scope: Scope) -> StdValue:
        """参数绑定值 → StdValue：已解析（StdValue）直接用；RawAst 走 _resolve_value。"""
        if isinstance(value, STD_VALUE_TYPES):
            return value
        rv = self._resolve_value(value, path, scope)
        return rv if rv is not None else StdLiteral(kind='null', value=None)

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
                self._err('value.nesting_depth', {'max': MAX_NESTING_DEPTH}, raw.source, path)
                return None

            match raw:
                case LiteralValue(value=tok):
                    return self._convert_literal(tok)
                case DollarValue(name=n, type_cast=tc, source=src):
                    return self._resolve_dollar(n, tc, path, src)
                case DictValue(fields=fs, constraints=cs, unpacks=ups):
                    std_fields: list[StdField] = []
                    # **expr 解包：目标必须是 dict，展开为键值对（disjoint merge 查重在 _finalize_object）
                    for up in ups:
                        rv = self._resolve_value(up.value, path, scope)
                        fields = self._unpack_dict(rv, up.source, path)
                        if fields is not None:
                            std_fields.extend(fields)
                    for f in fs:
                        child = f'{path}.{f.name}' if path else f.name
                        sf = self._build_field(f, path=child, scope=scope)
                        if sf is not None:
                            std_fields.append(sf)
                    # dict 结构级约束（作用于该字面量整体）：解析后挂节点，不执行
                    specs, diags = resolve_constraint_list(cs, scope)
                    self._collector.extend(diags)
                    return StdObject(fields=self._finalize_object(std_fields, path), constraints=specs)
                case ArrayValue(elements=els):
                    std_elements: list[StdValue] = []
                    for i, e in enumerate(els):
                        if isinstance(e, UnpackValue):
                            # *expr 解包：目标必须是 list，展开为元素
                            rv = self._resolve_value(e.value, f'{path}[*]', scope)
                            items = self._unpack_list(rv, e.source, path)
                            if items is not None:
                                std_elements.extend(items)
                            continue
                        rv = self._resolve_value(e, f'{path}[{i}]', scope)
                        if rv is None:
                            continue
                        std_elements.append(self._array_noexist(rv, e.source, f'{path}[{i}]'))
                    return StdArray(elements=std_elements)
                case TemplateCallValue(
                    template_name=tn,
                    positional_args=pa,
                    named_args=na,
                    unpack_args=upa,
                    unpack_kwargs=upk,
                ):
                    return self._expand_template_call(tn, pa, na, upa, upk, path, raw.source, scope)
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

    def _resolve_dollar(
        self, name: str, type_cast: str | None, path: str, source: SourceRange | None = None
    ) -> StdValue:
        """解析 ``$name`` 引用，type_cast 为显式 as bool/int/float/str 转换。

        source 为 ``$name`` 表达式在源码中的位置
        """
        if name not in self._namespace:
            self._warn('dollar.undefined', {'name': name}, source, path)
            return StdLiteral(kind='null', value=None)

        raw = self._namespace[name]
        # namespace 统一存 StdValue（!env/!file/!var 均由 python_to_std / 求值产出）
        if type_cast is None:
            return raw
        if isinstance(raw, (StdArray, StdObject)):
            return raw  # 结构化值 cast 不适用
        raw = raw.value  # StdLiteral：提取 Python 值走转换

        match type_cast:
            case 'bool':
                if isinstance(raw, bool):
                    val: bool = raw
                elif isinstance(raw, str):
                    low = raw.lower()
                    if low in ('true', '1'):
                        val = True
                    elif low in ('false', '0'):
                        val = False
                    else:
                        self._collector.add(
                            Diagnostic(
                                Severity.WARNING,
                                'dollar.convert_failed',
                                {'name': name, 'raw': raw, 'type': 'bool'},
                                source,
                                path,
                            )
                        )
                        val = False
                elif isinstance(raw, (int, float)):
                    val = bool(raw)
                else:
                    self._collector.add(
                        Diagnostic(
                            Severity.WARNING,
                            'dollar.convert_failed',
                            {'name': name, 'raw': raw, 'type': 'bool'},
                            source,
                            path,
                        )
                    )
                    val = False
                return StdLiteral(kind='bool', value=val)
            case 'int':
                try:
                    return StdLiteral(kind='int', value=int(cast(Any, raw)))
                except (ValueError, TypeError):
                    self._collector.add(
                        Diagnostic(
                            Severity.WARNING,
                            'dollar.convert_failed',
                            {'name': name, 'raw': raw, 'type': 'int'},
                            source,
                            path,
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
                            source,
                            path,
                        )
                    )
                    return StdLiteral(kind='float', value=decimal.Decimal(0))
            case 'str':
                return StdLiteral(kind='str', value=str(raw))
            case _:
                return StdLiteral(kind='str', value=str(raw))

    # ═══════════════════════════════════════════════════════
    # 模板展开
    # ═══════════════════════════════════════════════════════

    def _expand_template_call(
        self,
        template_name: str,
        positional_args: list[Value],
        named_args: dict[str, Value],
        unpack_args: list[UnpackValue],
        unpack_kwargs: list[UnpackValue],
        path: str,
        source: SourceRange | None,
        scope: Scope,
    ) -> StdValue:
        """展开模板调用为 StdObject（名字经调用点 scope 翻译，展开用模板定义点 scope）。

        字段 / 模板级约束解析后挂到节点（不执行），由执行器统一校验。
        解包：``*expr``（list → 位置参数）/ ``**expr``（dict → 命名参数）；
        解包键与已有参数冲突 → ``dict.duplicate_key``（disjoint merge，§2.7）。
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

        # ── 位置参数：显式 + *expr 解包（list → 逐个位置参数）──
        expanded_positional: list[Value | StdValue] = list(positional_args)
        for up in unpack_args:
            rv = self._resolve_value(up.value, path, scope)
            items = self._unpack_list(rv, up.source, path)
            if items is not None:
                expanded_positional.extend(items)

        # 模板配置 positional=false：位置参数违规报错，但值仍绑定必填字段
        # （放宽必填绑定：只报 positional_disabled 一条，避免 missing_required 级联）
        if not template.config.positional and expanded_positional:
            self._collector.add(
                Diagnostic(
                    Severity.ERROR,
                    'template.positional_disabled',
                    {'template': template_name},
                    source,
                    path,
                )
            )

        # ── 命名参数：显式 + **expr 解包（dict → 键值对）──
        # 未知命名参数：extra_named_vars 收集（与 allow_extra 互斥）；否则 allow_extra/报错
        declared = {tf.name for tf in template.fields}
        named_vars = template.config.extra_named_vars
        if named_vars is not None and named_vars not in declared:
            named_vars = None  # 定义时已报 variadic_target_missing（_check_variadic_config）
        param_values: dict[str, Value | StdValue] = dict(named_args)
        extra_args: dict[str, tuple[Value | StdValue, SourceRange | None]] = {}
        extra_named: dict[str, Value | StdValue] = {}
        for name, arg_val in named_args.items():
            if name not in declared:
                if named_vars is not None:
                    extra_named[name] = arg_val
                elif template.config.allow_extra:
                    extra_args[name] = (arg_val, arg_val.source)
                else:
                    self._err(
                        'template.unknown_argument',
                        {'template': template_name, 'arg': name},
                        source,
                        path,
                    )
        for up in unpack_kwargs:
            rv = self._resolve_value(up.value, path, scope)
            fields = self._unpack_dict(rv, up.source, path)
            if fields is None:
                continue
            for f in fields:
                if f.value is None:
                    continue  # 防御：解包字段值缺失（理论不可达）
                child = f'{path}.{f.name}' if path else f.name
                if f.name in param_values or f.name in extra_args:
                    # 解包键与已有参数冲突 → 重复键（disjoint merge）
                    self._err('dict.duplicate_key', {'name': f.name}, up.source, child)
                    continue
                if f.name not in declared:
                    if named_vars is not None:
                        extra_named[f.name] = f.value
                    elif template.config.allow_extra:
                        extra_args[f.name] = (f.value, f.source)
                    else:
                        self._err(
                            'template.unknown_argument',
                            {'template': template_name, 'arg': f.name},
                            up.source,
                            child,
                        )
                else:
                    param_values[f.name] = f.value
        if named_vars is not None and extra_named:
            # 收集未声明命名参数为 dict 字段（约束由字段声明承担，§2.9）
            param_values[named_vars] = StdObject(
                fields=[
                    StdField(name=k, value=self._bind_to_std(v, f'{path}.{k}', scope)) for k, v in extra_named.items()
                ]
            )

        # 参数映射：位置参数按定义顺序绑定必填字段；多余 → 收集（extra_positional_vars）或警告
        positional_vars = template.config.extra_positional_vars
        if positional_vars is not None and positional_vars not in declared:
            positional_vars = None  # 定义时已报 variadic_target_missing
        if positional_vars is not None and not template.config.positional:
            positional_vars = None  # 定义时已报 variadic_positional_conflict
        extra_pos: list[Value | StdValue] = []
        for idx, pos_val in enumerate(expanded_positional):
            if idx < len(required):
                rf = required[idx]
                if rf.name in param_values:
                    self._err(
                        'template.arg_conflict',
                        {'template': template_name, 'field': rf.name},
                        source,
                        path,
                    )
                else:
                    param_values[rf.name] = pos_val
            elif positional_vars is not None:
                extra_pos.append(pos_val)
            else:
                self._warn(
                    'template.too_many_positional',
                    {'template': template_name, 'count': len(required), 'given': len(expanded_positional)},
                    source,
                    path,
                )
        if positional_vars is not None and extra_pos:
            # 收集多余位置参数为 list 字段（约束由字段声明承担，§2.9）
            param_values[positional_vars] = StdArray(
                elements=[self._bind_to_std(x, f'{path}[{i}]', scope) for i, x in enumerate(extra_pos)]
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
                pv = param_values[tf.name]
                v = self._bind_to_std(pv, child, scope)
            elif tf.default_value is not None:
                v = self._resolve_value(tf.default_value, child, inner_scope)
            else:
                continue  # 必填且未提供 → 已在上面报错

            specs, diags = resolve_constraints(tf.constraints, inner_scope)
            self._collector.extend(diags)
            std_fields.append(StdField(name=tf.name, value=v, source=tf.source, constraints=specs))

        # allow_extra=true：额外字段作为扩展字段进入内容（按调用点 scope 解析）
        for name, (arg_val, arg_src) in extra_args.items():
            child = f'{path}.{name}' if path else name
            v = self._bind_to_std(arg_val, child, scope)
            std_fields.append(StdField(name=name, value=v, source=arg_src))

        # 模板级约束（: 起始，约束整个 dict）：解析后挂到实例节点
        tpl_specs, tpl_diags = resolve_constraint_list(template.constraints, inner_scope)
        self._collector.extend(tpl_diags)
        return StdObject(fields=self._finalize_object(std_fields, path), template=key, constraints=tpl_specs)
