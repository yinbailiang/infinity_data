"""内置类型约束：object / ? / int / str / bool / float / list / dict。"""

from __future__ import annotations

from typing import Any

from infinity_data.semantic.models import StdArray, StdLiteral, StdObject, StdValue
from infinity_data.semantic.registry._core import (
    ConstraintResult,
    Executor,
    describe,
    fail_result,
    ok_result,
)
from infinity_data.tokenizer.models.raw_tokens import SourceRange

__all__ = [
    '_check_object',
    '_check_nullable',
    '_check_int',
    '_check_float',
    '_check_str',
    '_check_bool',
    '_check_list',
    '_check_dict',
]


def _check_object(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'object'}, source, path)
    return ok_result()


def _check_nullable(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if isinstance(val, StdLiteral) and val.kind in ('null', 'noexist'):
        return ok_result()
    return fail_result(
        'constraint.type_mismatch', {'expected': 'noexist 或 null', 'actual': describe(val)}, source, path
    )


def _check_int(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'int'}, source, path)
    if isinstance(val, StdLiteral) and val.kind == 'int':
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'int', 'actual': describe(val)}, source, path)


def _check_float(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'float'}, source, path)
    if isinstance(val, StdLiteral) and val.kind == 'float':
        return ok_result()  # 含 NaN / ±Infinity
    return fail_result('constraint.type_mismatch', {'expected': 'float', 'actual': describe(val)}, source, path)


def _check_str(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'str'}, source, path)
    if isinstance(val, StdLiteral) and val.kind == 'str':
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'str', 'actual': describe(val)}, source, path)


def _check_bool(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'bool'}, source, path)
    if isinstance(val, StdLiteral) and val.kind == 'bool':
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'bool', 'actual': describe(val)}, source, path)


def _check_list(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'list'}, source, path)
    if isinstance(val, StdArray):
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'list', 'actual': describe(val)}, source, path)


def _check_dict(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'dict'}, source, path)
    if isinstance(val, StdObject):
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'dict', 'actual': describe(val)}, source, path)
