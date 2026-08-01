"""语义分析器：RawAst → StandardAst。

执行顺序：
1. 收集模板定义
2. 展开模板调用（宏展开）
3. 解析裸 key（key → key: <?> = exist）
4. 执行约束链
5. 填充默认值
6. 输出 StandardAst
"""

from __future__ import annotations

from infinity_data.analyzer.constraints import (
    ConstraintRegistry,
    ConstraintResult,
    apply_constraint_by_name,
    make_diagnostic,
)
from infinity_data.analyzer.models import (
    Diagnostic,
    StdArray,
    StdDocument,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.parser.models import (
    ArrayValue,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Document,
    Field,
    ImportStmt,
    LiteralValue,
    ObjectValue,
    TemplateCallValue,
    TemplateDef,
    TypeAnnotation,
    Value,
)
from infinity_data.tokenizer.models import SourceInfo


class SemanticAnalyzer:
    """语义分析器：将 RawAst 转换为 StandardAst。"""

    def __init__(self, registry: ConstraintRegistry | None = None) -> None:
        self._registry = registry or ConstraintRegistry()
        self._templates: dict[str, TemplateDef] = {}
        self._diagnostics: list[Diagnostic] = []

    # ── 公开入口 ─────────────────────────────────────────

    def analyze(self, doc: Document) -> StdDocument:
        """主入口：分析 RawAst，返回 StandardAst。"""
        self._diagnostics = []
        self._templates = {}

        # 第一遍：收集模板定义
        self._collect_templates(doc)

        # 第二遍：分析语句
        root_fields: list[StdField] = []
        for stmt in doc.statements:
            match stmt:
                case TemplateDef():
                    continue  # 模板定义不产生输出
                case ImportStmt():
                    continue  # 导入语句已解析（TODO: 实际加载）
                case Field():
                    result = self._analyze_field(stmt, path=stmt.name)
                    if result is not None:
                        root_fields.append(result)

        return StdDocument(
            root=StdObject(fields=root_fields),
            diagnostics=self._diagnostics,
        )

    # ── 模板收集 ─────────────────────────────────────────

    def _collect_templates(self, doc: Document) -> None:
        for stmt in doc.statements:
            if isinstance(stmt, TemplateDef):
                if stmt.name in self._templates:
                    self._warn(f"模板 {stmt.name!r} 重复定义，后者覆盖前者", stmt.source)
                self._templates[stmt.name] = stmt

    # ── 字段分析 ─────────────────────────────────────────

    def _analyze_field(self, field: Field, path: str) -> StdField | None:
        """分析单个字段，返回 StdField。"""

        # 1. 解析值
        value = self._resolve_value(field.value, path)

        # 2. 裸 key 处理：无类型无值 → exist 标记
        if field.type_annotation is None and value is None:
            value = StdLiteral(kind="exist", value="exist")

        # 3. 约束执行
        if field.type_annotation is not None:
            value = self._apply_constraints(field.type_annotation, value, field.source, path)

        return StdField(name=field.name, value=value, source=field.source)

    # ── 值解析 ───────────────────────────────────────────

    def _resolve_value(self, raw: Value | None, path: str) -> StdValue | None:
        """将 RawAst Value 转换为 StdValue。"""
        if raw is None:
            return None

        match raw:
            case LiteralValue(kind=k, raw=r):
                return self._convert_literal(k, r)
            case ObjectValue(fields=fs):
                std_fields: list[StdField] = []
                for f in fs:
                    child_path = f"{path}.{f.name}" if path else f.name
                    result = self._analyze_field(f, path=child_path)
                    if result is not None:
                        std_fields.append(result)
                return StdObject(fields=std_fields)
            case ArrayValue(elements=els):
                std_elements: list[StdValue] = []
                for i, e in enumerate(els):
                    elem_path = f"{path}[{i}]"
                    resolved = self._resolve_value(e, elem_path)
                    if resolved is not None:
                        std_elements.append(resolved)
                return StdArray(elements=std_elements)
            case TemplateCallValue(template_name=tn, positional_args=pa, named_args=na, source=src):
                return self._expand_template_call(tn, pa, na, path, src)
            case _:
                self._warn(f"{path}: 未知值类型", None)
                return None

    def _convert_literal(self, kind: str, raw: str) -> StdLiteral:
        """将 RawAst 字面量转为 StdLiteral（含 Python 值转换）。"""
        match kind:
            case "str":
                return StdLiteral(kind="str", value=raw)
            case "int":
                return StdLiteral(kind="int", value=int(raw))
            case "float":
                return StdLiteral(kind="float", value=float(raw))
            case "true":
                return StdLiteral(kind="bool", value=True)
            case "false":
                return StdLiteral(kind="bool", value=False)
            case "null":
                return StdLiteral(kind="null", value=None)
            case "exist":
                return StdLiteral(kind="exist", value="exist")
            case _:
                return StdLiteral(kind=kind, value=raw)

    # ── 模板展开 ─────────────────────────────────────────

    def _expand_template_call(
        self,
        template_name: str,
        positional_args: list[Value],
        named_args: dict[str, Value],
        path: str,
        source: SourceInfo | None,
    ) -> StdValue:
        """展开模板调用为 StdObject。"""
        template = self._templates.get(template_name)
        if template is None:
            self._err(f"{path}: 未定义的模板 {template_name!r}", None)
            return StdObject()

        # 构建参数映射：位置参数在前，命名参数在后
        param_values: dict[str, Value] = dict(named_args)

        # 位置参数按模板定义顺序绑定
        for idx, pos_val in enumerate(positional_args):
            if idx < len(template.body):
                body_field = template.body[idx]
                if isinstance(body_field, Field):
                    if body_field.name not in param_values:
                        param_values[body_field.name] = pos_val

        # 展开模板 body
        std_fields: list[StdField] = []
        for stmt in template.body:
            if isinstance(stmt, Field):
                child_path = f"{path}.{stmt.name}" if path else stmt.name
                # 用传入参数覆盖默认值
                if stmt.name in param_values:
                    override_val = self._resolve_value(param_values[stmt.name], f"{child_path}")
                    # 参数覆盖的值也要经过约束检查
                    if stmt.type_annotation is not None and override_val is not None:
                        override_val = self._apply_constraints(
                            stmt.type_annotation, override_val, stmt.source, f"{child_path}"
                        )
                    std_fields.append(StdField(name=stmt.name, value=override_val, source=stmt.source))
                else:
                    # 使用模板默认值
                    field_result = self._analyze_field(stmt, path=child_path)
                    if field_result is not None:
                        # 模板字段如果无默认值且未被覆盖 → 保持原样（值可能为 None）
                        std_fields.append(field_result)

        return StdObject(fields=std_fields)

    # ── 约束执行 ─────────────────────────────────────────

    def _apply_constraints(
        self,
        annotation: TypeAnnotation,
        value: StdValue | None,
        source: SourceInfo | None,
        path: str,
    ) -> StdValue | None:
        """对值依次执行约束链，返回（可能被强制转换的）值。

        约束执行顺序：
        1. 若 nullable 且值为 null → 直接通过，跳过其他约束
        2. 依次执行约束链中的每个约束
        """
        if not annotation.constraints:
            return value

        # 可空优先：null 值 + nullable → 跳过所有约束
        if annotation.nullable:
            if isinstance(value, StdLiteral) and value.kind == "null":
                return value

        current = value
        for constraint in annotation.constraints:
            result = self._execute_constraint(constraint, current, source, path)
            if not result.ok:
                self._diagnostics.extend(result.diagnostics)
                # 约束失败后不继续执行后续约束（一个失败就停）
                return current
            if result.coerced_value is not None:
                current = result.coerced_value

        return current

    def _execute_constraint(
        self,
        constraint: object,
        value: StdValue | None,
        source: SourceInfo | None,
        path: str,
    ) -> ConstraintResult:
        """执行单个约束。"""
        match constraint:
            case ConstraintIdent(name=n):
                return apply_constraint_by_name(n, value, source, path, [])
            case ConstraintCall(name=n, arguments=args):
                resolved_args = [self._resolve_constraint_arg(a) for a in args]
                return apply_constraint_by_name(n, value, source, path, resolved_args)
            case _:
                return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 未知约束类型", source, path)])

    def _resolve_constraint_arg(self, arg: object) -> object:
        """解析约束参数（约束内部可能嵌套标识符或字面量）。"""
        if isinstance(arg, ConstraintIdent):
            # 约束参数中的标识符——通常是类型名（如 each(str) 中的 str）
            return arg.name
        if isinstance(arg, ConstraintLiteral):
            match arg.kind:
                case "str":
                    return arg.raw
                case "int":
                    return int(arg.raw)
                case "float":
                    return float(arg.raw)
                case "true":
                    return True
                case "false":
                    return False
                case "null":
                    return None
                case _:
                    return str(arg.raw)
        return str(arg)

    # ── 诊断辅助 ─────────────────────────────────────────

    def _err(self, msg: str, source: SourceInfo | None, path: str = "") -> None:
        self._diagnostics.append(Diagnostic(level="error", message=msg, source=source, path=path))

    def _warn(self, msg: str, source: SourceInfo | None, path: str = "") -> None:
        self._diagnostics.append(Diagnostic(level="warning", message=msg, source=source, path=path))
