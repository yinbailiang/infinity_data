"""内置字典约束：has / field。

与三态可空的交互：``noexist`` 字段（键不出现）对二者均视为**不存在**——
``has(noexist字段)`` 不满足、``field(noexist字段, c)`` 视为字段缺失。
（noexist 在 StdObject 中是非 None 哨兵，渲染时才过滤，须显式排除。）
"""

from __future__ import annotations

from typing import Any

from infinity_data.semantic.builder.models import StdObject
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

__all__ = ['_check_field', '_check_has']


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
    f = val.get(key)
    # noexist 字段在 StdObject 中仍以非 None 哨兵存在（渲染时才过滤），
    # 但按三态语义「键不出现」应视为不存在（回归：one(has(a), has(b)) 误判 both）。
    if f is not None and not f.is_noexist:
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
    # noexist = 键不出现 → 视为字段缺失（与 has 同理）
    if f is None or f.is_noexist:
        return fail_result('constraint.field_missing', {'field': name}, source, path)
    return executor(spec, f.value, source, f'{path}.{name}')
