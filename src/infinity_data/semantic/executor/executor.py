"""约束执行器（Phase 2b）：遍历已完成 StdAst，执行节点携带的约束。

约束器**工作在 AST 上**（不参与构建）：

- 递归遍历 :class:`StdField` / :class:`StdObject` / :class:`StdArray`，
  执行节点携带的 :class:`ResolvedConstraint`
  （字段注解 / dict 结构级 / 模板级 / 顶层结构约束）
- 「模板即约束」：约束名为模板真名时，查模板表做结构校验（手写 dict）
- **只校验、不转换**：约束失败仅产出诊断，不改变值（coercion 属错误设计）
- 顶层 schema 校验（strict/lenient/strip）也在此：
  对顶层对象执行模板约束 + 额外字段策略

本层消费 Phase 2a 数据模型（:class:`StdDocument` 等），与构建器零耦合；
诊断写入调用方注入的共享 :class:`DiagnosticCollector`（流水线单一收集器）。
"""

from __future__ import annotations

from infinity_data.infra.diagnostics import Diagnostic, DiagnosticCollector, Severity
from infinity_data.parser.models import TemplateDef
from infinity_data.sandbox import Schema, SchemaError
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
    ) -> None:
        self._registry = registry
        self._templates = templates
        self._template_scopes = template_scopes
        self._templates_by_name: dict[str, TemplateKey] = {str(k): k for k in templates}

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
                result = self._exec(spec, node, spec.source, path)
                if not result.ok:
                    collector.extend(result.diagnostics)
        elif isinstance(node, StdArray):
            for i, elem in enumerate(node.elements):
                self.validate(elem, collector, f'{path}[{i}]')

    def _validate_field(self, field: StdField, collector: DiagnosticCollector, path: str) -> None:
        """字段：先递归值（内部结构约束），再执行字段注解约束（链式短路）。"""
        child = f'{path}.{field.name}' if path else field.name
        if field.value is not None:
            self.validate(field.value, collector, child)
        for spec in field.constraints:
            result = self._exec(spec, field.value, spec.source or field.source, child)
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
        return self._registry.apply(constraint, value, constraint.source or source, path, self._exec)

    def _check_template(
        self,
        key: TemplateKey,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult:
        """模板即约束：校验手写 dict 是否符合模板声明（含字段 / 模板级约束）。"""
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

        # 逐字段校验（模板定义约束）
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
                specs, rdiags = resolve_constraints(tf.constraints, scope)
                diags.extend(rdiags)
                for spec in specs:
                    result = self._exec(spec, f.value, tf.source, child)
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

        - lenient 的额外字段 WARNING 写入 ``collector``（非致命）
        - strict / 必填缺失 / 字段 / 模板级约束失败聚合为 :class:`SchemaError` 抛出
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

        # 必填字段缺失
        for tf in tpl.fields:
            if tf.default_value is None and root.get(tf.name) is None:
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
            f = root.get(tf.name)
            if f is not None and f.value is not None:
                specs, rdiags = resolve_constraints(tf.constraints, scope)
                diags.extend(rdiags)
                for spec in specs:
                    result = self._exec(spec, f.value, tf.source, tf.name)
                    if not result.ok:
                        diags.extend(result.diagnostics)

        # 模板级约束
        specs, rdiags = resolve_constraint_list(tpl.constraints, scope)
        diags.extend(rdiags)
        for spec in specs:
            result = self._exec(spec, root, None, '')
            if not result.ok:
                diags.extend(result.diagnostics)

        if diags:
            raise SchemaError('schema.failed', {'detail': '；'.join(d.message for d in diags)})
        return root
