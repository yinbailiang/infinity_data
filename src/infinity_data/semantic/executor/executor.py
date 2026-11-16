"""约束执行器（Phase 2b）：遍历已完成 StdAst，执行节点携带的约束。

约束器**工作在 AST 上**（不参与构建）：

- 递归遍历 :class:`StdField` / :class:`StdObject` / :class:`StdArray`，
  执行节点携带的 :class:`ResolvedConstraint`
  （字段注解 / dict 结构级 / 模板级 / 顶层结构约束）
- 「模板即约束」：约束名为模板真名时，查模板表做结构校验（手写 dict）
- **只校验、不转换**：约束失败仅产出诊断，不改变值（coercion 属错误设计）
- 顶层 schema 校验（strict/lenient/strip）也在此：
  对顶层对象执行模板约束 + 额外字段策略
- 定义期静态校验：模板定义中的约束声明（名字 / 参数个数）无需实例化即可报错
  （:meth:`ConstraintExecutor.validate_templates`）

本层消费 Phase 2a 数据模型（:class:`StdDocument` 等），与构建器零耦合；
诊断写入调用方注入的共享 :class:`DiagnosticCollector`（流水线单一收集器）。
"""

from __future__ import annotations

from pathlib import Path

from infinity_data.infra.diagnostics import Diagnostic, DiagnosticCollector, Severity
from infinity_data.parser import TemplateDef, TemplateField
from infinity_data.sandbox import Sandbox, SandboxConfig, Schema, SchemaError
from infinity_data.semantic.builder.models import (
    ResolvedConstraint,
    StdArray,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.semantic.constraints import resolve_constraint_list, resolve_constraints
from infinity_data.semantic.registry import (
    ConstraintRegistry,
    ConstraintResult,
    describe,
    fail_result,
    ok_result,
)
from infinity_data.semantic.resolver.models import Scope, TemplateKey
from infinity_data.tokenizer.models.raw_tokens import SourceRange

_INVALID_CONSTRAINT = '@invalid'


class ConstraintExecutor:
    """工作在已完成 StdAst 上的约束遍历器：节点约束 → 诊断（只校验，不转换）。"""

    def __init__(
        self,
        *,
        registry: ConstraintRegistry,
        templates: dict[TemplateKey, TemplateDef],
        template_scopes: dict[TemplateKey, Scope],
        sandbox: Sandbox | None = None,
    ) -> None:
        self._registry = registry
        self._templates = templates
        self._template_scopes = template_scopes
        self._templates_by_name: dict[str, TemplateKey] = {str(k): k for k in templates}
        # 零信任默认：文件系统依赖约束（exist/dir/file/link）经沙盒授权探测
        self._sandbox = sandbox or Sandbox(config=SandboxConfig.deny_all(), base_dir=Path.cwd())

    @property
    def sandbox(self) -> Sandbox:
        """沙盒中介：文件系统约束的授权探测通道（allow_files 白名单控制）。"""
        return self._sandbox

    def __call__(
        self,
        constraint: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult:
        """嵌套约束执行回调（:class:`Executor` 协议）：委托给 :meth:`_exec`，
        使约束函数能经 ``executor.sandbox`` 访问沙盒。"""
        return self._exec(constraint, value, source, path)

    # ═══════════════════════════════════════════════════════
    # 遍历入口
    # ═══════════════════════════════════════════════════════

    def validate(self, node: StdValue, collector: DiagnosticCollector, path: str = '') -> None:
        """递归遍历节点，执行携带的约束，诊断写入 ``collector``（不修改值）。"""
        if isinstance(node, StdObject):
            for f in node.fields:
                self._validate_field(f, collector, path)
            # 结构级约束（dict 级 / 模板级 / 顶层）：全部执行（不短路）
            for spec in node.constraints:
                # 诊断指向被检查的对象本身（无来源时回退约束表达式位置）
                result = self._exec(spec, node, node.source or spec.source, path)
                if not result.ok:
                    collector.extend(result.diagnostics)
        elif isinstance(node, StdArray):
            for i, elem in enumerate(node.elements):
                self.validate(elem, collector, f'{path}[{i}]')

    def validate_templates(self, collector: DiagnosticCollector) -> None:
        """静态校验模板定义中的约束声明（名字 / 参数个数），不执行约束。

        模板字段约束只在实例化时执行——未被实例化的模板里的非法声明
        （未知约束名 ``constraint.unknown``、参数个数不符 ``constraint.arg_count``）
        否则永远不会被发现。仅检查**顶层**约束声明：部分约束参数是名字而非约束
        （``has(x)`` / ``field(x, c)``），静态层无法区分，嵌套约束仍在执行时校验。

        被实例化的模板会再次在调用点报出同一问题（定义点 + 使用点），
        两个位置都指向真实错误。
        """
        for key, tpl in self._templates.items():
            scope = self._template_scopes.get(key)
            if scope is None:
                continue
            for tf in tpl.fields:
                specs, diags = resolve_constraints(tf.constraints, scope)
                collector.extend(diags)
                for spec in specs:
                    self._check_static_signature(spec, collector)
            specs, diags = resolve_constraint_list(tpl.constraints, scope)
            collector.extend(diags)
            for spec in specs:
                self._check_static_signature(spec, collector)

    def _check_static_signature(self, spec: ResolvedConstraint, collector: DiagnosticCollector) -> None:
        """单个约束声明的静态签名校验（模板真名与无效占位符跳过）。"""
        if spec.name == _INVALID_CONSTRAINT or spec.name in self._templates_by_name:
            return
        entry = self._registry.lookup(spec.name)
        if entry is None:
            collector.add(Diagnostic(Severity.ERROR, 'constraint.unknown', {'name': spec.name}, spec.source))
            return
        expected = entry.arity_error(len(spec.args))
        if expected is not None:
            collector.add(
                Diagnostic(
                    Severity.ERROR,
                    'constraint.arg_count',
                    {'name': spec.name, 'expected': expected, 'given': len(spec.args)},
                    spec.source,
                )
            )

    def validate_template_defaults(
        self,
        defaults: dict[TemplateKey, list[StdField]],
        collector: DiagnosticCollector,
    ) -> None:
        """校验模板字段默认值（定义期，不依赖实例化）。

        默认值只在模板实例化时才会被求值/执行约束：仅作为校验器使用或从未
        实例化的模板，非法默认值（类型不符 / 嵌套模板缺参等）否则永远静默。
        默认值由 Phase 2a 按定义点 scope 求值（:class:`AstBuilder`），本层只执行。
        诊断路径为 ``Template.field``。
        """
        for key, fields in defaults.items():
            for field in fields:
                self._validate_field(field, collector, key.name)

    def validate_var_values(self, values: list[tuple[str, StdValue]], collector: DiagnosticCollector) -> None:
        """校验 ``!var`` 求值结果携带的约束（编译期，不依赖是否被引用）。

        ``!var`` 值（模板展开 / dict 字面量）挂载的约束原本只随 root 遍历执行，
        var 值不进入 root 时永远静默。诊断路径显示为 ``$别名``（按定义文件
        就地命名空间），位置指向求值表达式。
        """
        for name, value in values:
            self.validate(value, collector, name)

    def _validate_field(self, field: StdField, collector: DiagnosticCollector, path: str) -> None:
        """字段：先递归值（内部结构约束），再执行字段注解约束（链式短路）。"""
        child = f'{path}.{field.name}' if path else field.name
        if field.value is not None:
            self.validate(field.value, collector, child)
        # 被检查对象 = 字段值：诊断指向值本身（无来源时回退字段位置）
        value_src = field.value.source if field.value is not None else None
        for spec in field.constraints:
            result = self._exec(spec, field.value, value_src or field.source, child)
            if not result.ok:
                collector.extend(result.diagnostics)
                break  # 约束链短路（与构建期语义一致）

    # ═══════════════════════════════════════════════════════
    # 约束执行
    # ═══════════════════════════════════════════════════════

    def _exec(
        self,
        constraint: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult:
        """执行单个已解析约束；模板真名 → 模板结构校验；其余 → registry。

        签名与 :class:`Executor` 协议一致（嵌套约束回调复用本方法）。
        """
        if constraint.name == _INVALID_CONSTRAINT:
            return fail_result('constraint.invalid', {}, source, path)
        key = self._templates_by_name.get(constraint.name)
        if key is not None:
            return self._check_template(key, value, source, path)
        # 诊断位置 = 被检查对象的位置（调用方已按值/字段/对象解析），
        # 不再取约束表达式自身（spec.source）——错误指向值而非约束声明
        return self._registry.apply(constraint, value, source, path, self)

    def _accepts_absent(self, tf: TemplateField, scope: Scope) -> bool:
        """字段约束是否接受 noexist（``!``）：对合成 noexist 值执行，诊断丢弃。

        直接复用约束语义（``any(T, !)`` / ``one(...)`` 等天然正确），不做静态
        组合分析。仅在字段缺失时调用，失败诊断不对外汇报。
        """
        specs, _ = resolve_constraints(tf.constraints, scope)
        if not specs:
            return False  # 空约束列表不接受任何值（含 noexist）
        absent = StdLiteral(kind='noexist', value=None)
        return all(self._exec(spec, absent, spec.source, '').ok for spec in specs)

    def _check_template(
        self,
        key: TemplateKey,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult:
        """模板即约束：校验手写 dict 是否符合模板声明（含字段 / 模板级约束）。

        完整形状：字段必须声明；约束接受 noexist（``!``）的字段可缺失。
        """
        tpl = self._templates[key]
        display = key.name
        scope = self._template_scopes[key]
        allow_extra = tpl.config.allow_extra
        declared = {tf.name for tf in tpl.fields}

        if value is None:
            return fail_result('template.expect_value', {'template': display}, source, path)
        if isinstance(value, StdLiteral):
            if value.kind == 'null':
                return fail_result('template.null_use_nullable', {'template': display}, source, path)
            return fail_result('template.expect_object', {'template': display, 'actual': describe(value)}, source, path)
        if not isinstance(value, StdObject):
            return fail_result('template.expect_object', {'template': display, 'actual': describe(value)}, source, path)

        # 标记来源模板：这个手写 dict 被判定为模板 display 的结构（供下游引用）
        if value.template is None:
            value.template = key

        diags: list[Diagnostic] = []
        field_map = {f.name: f for f in value.fields}

        # 逐字段校验（模板定义约束）；完整形状：约束接受 noexist（!）的字段可缺失
        for tf in tpl.fields:
            child = f'{path}.{tf.name}' if path else tf.name
            f = field_map.get(tf.name)
            if f is None:
                if self._accepts_absent(tf, scope):
                    continue  # `!`：字段可缺失
                code = 'template.missing_field' if tf.default_value is None else 'template.missing_optional'
                diags.append(Diagnostic(Severity.ERROR, code, {'template': display, 'field': tf.name}, source, child))
                continue
            if f.value is not None:
                specs, rdiags = resolve_constraints(tf.constraints, scope)
                diags.extend(rdiags)
                for spec in specs:
                    # 诊断指向手写 dict 中被检查的字段值（而非模板定义里的约束）；
                    # 值/字段均无来源（如外部导入数据）时回退外层被检查对象位置
                    result = self._exec(spec, f.value, f.value.source or f.source or source, child)
                    if not result.ok:
                        diags.extend(result.diagnostics)
                        break

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
        specs, rdiags = resolve_constraint_list(tpl.constraints, scope)
        diags.extend(rdiags)
        for spec in specs:
            result = self._exec(spec, value, source, path)
            if not result.ok:
                diags.extend(result.diagnostics)

        if diags:
            return ConstraintResult(ok=False, diagnostics=diags)
        return ok_result()

    # ═══════════════════════════════════════════════════════
    # 顶层 schema 校验
    # ═══════════════════════════════════════════════════════

    def apply_schema(
        self,
        root: StdObject,
        schema: Schema,
        tpl: TemplateDef,
        scope: Scope,
        collector: DiagnosticCollector,
    ) -> StdObject:
        """按模板校验顶层对象（strict/lenient/strip），返回校验后的 root。

        校验器要求完整形状：字段缺失（含可选字段）一律失败；
        - lenient 的额外字段 WARNING 写入 ``collector``（非致命）
        - strict / 字段缺失 / 字段 / 模板级约束失败聚合为 :class:`SchemaError` 抛出
        """
        mode = schema.mode
        declared = {tf.name for tf in tpl.fields}
        diags: list[Diagnostic] = []

        # 额外字段处理（模式差异）
        extra_names = [f.name for f in root.fields if f.name not in declared]
        if extra_names:
            if mode == 'strict':
                diags.append(Diagnostic(Severity.ERROR, 'schema.extra_fields', {'fields': extra_names}, None))
            elif mode == 'lenient':
                collector.add(
                    Diagnostic(Severity.WARNING, 'schema.extra_fields_lenient', {'fields': extra_names}, None)
                )
            else:  # strip
                root = StdObject(fields=[f for f in root.fields if f.name in declared], template=root.template)

        # 字段缺失（完整形状：约束接受 noexist 的字段可缺失）
        for tf in tpl.fields:
            if root.get(tf.name) is None:
                if self._accepts_absent(tf, scope):
                    continue
                code = 'schema.missing_required' if tf.default_value is None else 'schema.missing_optional'
                diags.append(
                    Diagnostic(
                        Severity.ERROR,
                        code,
                        {'field': tf.name, 'template': tpl.name},
                        None,
                        tf.name,
                    )
                )

        # 字段约束校验
        for tf in tpl.fields:
            f = root.get(tf.name)
            if f is not None and f.value is not None:
                specs, rdiags = resolve_constraints(tf.constraints, scope)
                diags.extend(rdiags)
                for spec in specs:
                    # 诊断指向顶层对象中被检查的字段值（而非模板定义里的约束）
                    result = self._exec(spec, f.value, f.value.source or f.source, tf.name)
                    if not result.ok:
                        diags.extend(result.diagnostics)

        # 模板级约束
        specs, rdiags = resolve_constraint_list(tpl.constraints, scope)
        diags.extend(rdiags)
        for spec in specs:
            # 顶层对象无来源时回退约束表达式位置（避免丢位置）
            result = self._exec(spec, root, root.source or spec.source, '')
            if not result.ok:
                diags.extend(result.diagnostics)

        if diags:
            raise SchemaError('schema.failed', {'detail': '；'.join(d.message for d in diags)})
        return root
