"""内置逻辑约束：not / any / one / all / when。"""

from __future__ import annotations

from typing import Any

from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.semantic.models import StdValue
from infinity_data.semantic.registry._core import (
    ConstraintResult,
    Executor,
    fail_result,
    ok_result,
)
from infinity_data.semantic.registry._core import (
    as_spec as _as_spec,
)
from infinity_data.tokenizer.models.raw_tokens import SourceRange

__all__ = ['_check_not', '_check_any', '_check_one', '_check_all', '_check_when']


def _check_not(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    spec = _as_spec(args[0])
    if spec is None:
        return fail_result('constraint.not_need', {}, source, path)
    inner = executor(spec, val, source, path)
    if not inner.ok:
        return ok_result()  # 内部不满足 → not 满足
    return fail_result('constraint.not_fail', {}, source, path)


def _check_any(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    diags: list[Diagnostic] = []
    for arg in args:
        spec = _as_spec(arg)
        if spec is None:
            continue
        inner = executor(spec, val, source, path)
        if inner.ok:
            return ok_result()
        diags.extend(inner.diagnostics)
    return ConstraintResult(
        ok=False,
        diagnostics=[
            Diagnostic(Severity.ERROR, 'constraint.any_fail', {}, source, path),
            *diags,
        ],
    )


def _check_one(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    satisfied: list[str] = []
    diags: list[Diagnostic] = []
    for arg in args:
        spec = _as_spec(arg)
        if spec is None:
            continue
        inner = executor(spec, val, source, path)
        if inner.ok:
            satisfied.append(spec.name)
        else:
            diags.extend(inner.diagnostics)
    if len(satisfied) == 1:
        return ok_result()
    if not satisfied:
        return ConstraintResult(
            ok=False,
            diagnostics=[
                Diagnostic(Severity.ERROR, 'constraint.one_none', {}, source, path),
                *diags,
            ],
        )
    return fail_result('constraint.one_many', {'count': len(satisfied), 'names': satisfied}, source, path)


def _check_all(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    diags: list[Diagnostic] = []
    for arg in args:
        spec = _as_spec(arg)
        if spec is None:
            continue
        inner = executor(spec, val, source, path)
        if not inner.ok:
            diags.extend(inner.diagnostics)
    if not diags:
        return ok_result()
    return ConstraintResult(
        ok=False,
        diagnostics=[
            Diagnostic(Severity.ERROR, 'constraint.all_fail', {}, source, path),
            *diags,
        ],
    )


def _check_when(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    cond = _as_spec(args[0])
    req = _as_spec(args[1])
    if cond is None or req is None:
        return fail_result('constraint.when_need', {}, source, path)
    if not executor(cond, val, source, path).ok:
        return ok_result()  # 条件不满足 → 约束满足
    return executor(req, val, source, path)
