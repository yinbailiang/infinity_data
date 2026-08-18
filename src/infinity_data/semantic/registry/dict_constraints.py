"""内置字典约束：has / field。"""

from __future__ import annotations

from typing import Any

from infinity_data.semantic.models import StdObject
from infinity_data.semantic.registry._core import (
    ConstraintResult,
    Executor,
    fail_result,
    ok_result,
)
from infinity_data.semantic.registry._core import (
    as_spec as _as_spec,
)
from infinity_data.semantic.registry._core import (
    spec_name as _spec_name,
)
from infinity_data.tokenizer.models.raw_tokens import SourceRange

__all__ = ['_check_has', '_check_field']


def _check_has(
    val: Any,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if not isinstance(val, StdObject):
        return fail_result('constraint.has_only', {}, source, path)
    key = _spec_name(args[0])
    if val.get(key) is not None:
        return ok_result()
    return fail_result('constraint.has_missing', {'key': key}, source, path)


def _check_field(
    val: Any,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if not isinstance(val, StdObject):
        return fail_result('constraint.field_only', {}, source, path)
    name = _spec_name(args[0])
    spec = _as_spec(args[1])
    if spec is None:
        return fail_result('constraint.field_need', {}, source, path)
    f = val.get(name)
    if f is None:
        return fail_result('constraint.field_missing', {'field': name}, source, path)
    return executor(spec, f.value, source, f'{path}.{name}')
