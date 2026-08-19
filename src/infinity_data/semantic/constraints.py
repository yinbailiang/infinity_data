"""约束解析：RawAst 约束 → :class:`ResolvedConstraint`（挂在 StdAst 节点上）。

纯函数、无副作用：解析约束 AST（名字经 scope 翻译为真名、参数求值），
返回 ``(specs, diagnostics)``——``ErrorConstraint`` 的诊断在此收集返回，
不直接写入任何收集器（调用方自行并入）。

约束**只解析不执行**：执行由 :class:`ConstraintExecutor`（Phase 2b）完成。
"""

from __future__ import annotations

from typing import Any

from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.parser.models import (
    Constraint,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Constraints,
    ErrorConstraint,
    LiteralValue,
)
from infinity_data.semantic.builder.models import ResolvedConstraint
from infinity_data.semantic.resolver.models import Scope
from infinity_data.tokenizer.models.tokens import (
    BoolToken,
    FloatToken,
    IntegerToken,
    NoexistToken,
    NullToken,
    StringToken,
)

_INVALID_CONSTRAINT = '@invalid'


def expand_annotation(annotation: Constraints) -> Constraints:
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


def resolve_constraints(
    annotation: Constraints,
    scope: Scope,
) -> tuple[list[ResolvedConstraint], list[Diagnostic]]:
    """解析字段注解约束链（语法糖展开 → 逐约束解析），返回 ``(specs, diagnostics)``。"""
    expanded = expand_annotation(annotation)
    specs: list[ResolvedConstraint] = []
    diags: list[Diagnostic] = []
    for c in expanded.constraints:
        spec, ds = resolve_constraint(c, scope)
        specs.append(spec)
        diags.extend(ds)
    return specs, diags


def resolve_constraint_list(
    constraints: list[Constraint],
    scope: Scope,
) -> tuple[list[ResolvedConstraint], list[Diagnostic]]:
    """解析结构级约束列表（dict 级 / 模板级 / 顶层 ``: <...>``），逐个解析。

    与字段注解（:class:`Constraints`）不同，结构约束已是展开后的列表：
    多约束是否合成 ``all`` 由 parser 决定，此处不再次展开。
    """
    specs: list[ResolvedConstraint] = []
    diags: list[Diagnostic] = []
    for c in constraints:
        spec, ds = resolve_constraint(c, scope)
        specs.append(spec)
        diags.extend(ds)
    return specs, diags


def resolve_constraint(c: Constraint, scope: Scope) -> tuple[ResolvedConstraint, list[Diagnostic]]:
    """解析单个约束 AST（名字经 scope 翻译为真名）。"""
    match c:
        case ConstraintIdent(name=n):
            return ResolvedConstraint(name=translate_name(n, scope), source=c.source), []
        case ConstraintCall(name=n, arguments=args):
            resolved_args: list[Any] = []
            diags: list[Diagnostic] = []
            for a in args:
                arg, ds = resolve_constraint_arg(a, scope)
                resolved_args.append(arg)
                diags.extend(ds)
            return (
                ResolvedConstraint(name=translate_name(n, scope), args=resolved_args, source=c.source),
                diags,
            )
        case ConstraintLiteral():
            return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source), []
        case ErrorConstraint(message=m):
            return (
                ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source),
                [Diagnostic(Severity.ERROR, 'error.generic', {'message': m}, c.source)],
            )
    return ResolvedConstraint(name=_INVALID_CONSTRAINT), []


def resolve_constraint_arg(c: Constraint, scope: Scope) -> tuple[Any, list[Diagnostic]]:
    """解析约束参数：嵌套约束 → ResolvedConstraint；字面量 → Python 值。"""
    match c:
        case ConstraintIdent(name=n):
            return ResolvedConstraint(name=translate_name(n, scope), source=c.source), []
        case ConstraintCall(name=n, arguments=args):
            resolved_args: list[Any] = []
            diags: list[Diagnostic] = []
            for a in args:
                arg, ds = resolve_constraint_arg(a, scope)
                resolved_args.append(arg)
                diags.extend(ds)
            return (
                ResolvedConstraint(name=translate_name(n, scope), args=resolved_args, source=c.source),
                diags,
            )
        case ConstraintLiteral(value=lit):
            return literal_python_value(lit), []
        case ErrorConstraint(message=m):
            return (
                ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source),
                [Diagnostic(Severity.ERROR, 'error.generic', {'message': m}, c.source)],
            )
    return ResolvedConstraint(name=_INVALID_CONSTRAINT), []


def translate_name(name: str, scope: Scope) -> str:
    """可见名 → 真名字符串。未命中（如 has(field) 的裸字段名）保留原名。"""
    key = scope.get(name)
    return str(key) if key is not None else name


def literal_python_value(lit: LiteralValue) -> Any:
    """约束参数字面量 → Python 值。"""
    match lit.value:
        case IntegerToken(value=v):
            return v
        case FloatToken(value=v):
            return v
        case BoolToken(value=v):
            return v
        case StringToken(value=v):
            return v
        case NullToken():
            return None
        case NoexistToken():
            return None
    return None
