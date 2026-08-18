"""内置一般约束：range / size / each / in / ip / regex / 格式 / 数值 / eq / unique。"""

from __future__ import annotations

import ipaddress
import re
import uuid
from typing import Any, cast
from urllib.parse import urlparse

from infinity_data.infra.diagnostics import Diagnostic
from infinity_data.semantic.models import StdArray, StdLiteral, StdObject, StdValue
from infinity_data.semantic.registry._core import (
    ConstraintResult,
    Executor,
    describe,
    fail_result,
    ok_result,
)
from infinity_data.semantic.registry._core import (
    as_decimal_arg as _as_decimal_arg,
)
from infinity_data.semantic.registry._core import (
    as_number as _as_number,
)
from infinity_data.semantic.registry._core import (
    as_spec as _as_spec,
)
from infinity_data.semantic.registry._core import (
    as_std_value as _as_std_value,
)
from infinity_data.semantic.registry._core import (
    as_str as _as_str,
)
from infinity_data.semantic.registry._core import (
    std_equal as _std_equal,
)
from infinity_data.tokenizer.models.raw_tokens import SourceRange

__all__ = [
    '_check_range',
    '_check_size',
    '_check_each',
    '_check_in',
    '_check_ip',
    '_check_ip4',
    '_check_ip6',
    '_check_regex',
    '_check_email',
    '_check_url',
    '_check_uuid',
    '_check_hostname',
    '_check_positive',
    '_check_negative',
    '_check_nonnegative',
    '_check_eq',
    '_check_unique',
]


def _check_range(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    num = _as_number(val)
    if num is None:
        return fail_result('constraint.numeric_only', {'constraint': 'range', 'actual': describe(val)}, source, path)
    if num.is_nan():
        return fail_result('constraint.nan_not_allowed', {'constraint': 'range'}, source, path)
    lo = _as_decimal_arg(args[0]) if args[0] is not None else None
    hi = _as_decimal_arg(args[1]) if len(args) > 1 and args[1] is not None else None
    if args[0] is not None and lo is None:
        return fail_result('constraint.range_arg', {'value': args[0]}, source, path)
    if len(args) > 1 and args[1] is not None and hi is None:
        return fail_result('constraint.range_arg', {'value': args[1]}, source, path)
    if lo is not None and num < lo:
        return fail_result('constraint.range_below', {'value': num, 'lo': lo}, source, path)
    if hi is not None and num > hi:
        return fail_result('constraint.range_above', {'value': num, 'hi': hi}, source, path)
    return ok_result()


def _check_size(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    size_val: int | None = None
    if isinstance(val, StdLiteral) and val.kind == 'str':
        v = val.value
        size_val = len(v) if isinstance(v, str) else None
    elif isinstance(val, StdArray):
        size_val = len(val.elements)
    elif isinstance(val, StdObject):
        size_val = len(val.fields)
    if size_val is None:
        return fail_result('constraint.size_only', {'actual': describe(val)}, source, path)
    lo = _as_decimal_arg(args[0])
    hi = _as_decimal_arg(args[1]) if len(args) > 1 else None
    if lo is None or (len(args) > 1 and hi is None):
        return fail_result('constraint.size_arg', {}, source, path)
    if size_val < lo or (hi is not None and size_val > hi):
        return fail_result('constraint.size_out', {'size': size_val, 'lo': lo, 'hi': hi}, source, path)
    return ok_result()


def _check_each(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    spec = _as_spec(args[0])
    if spec is None:
        return fail_result('constraint.each_need', {}, source, path)
    diags: list[Diagnostic] = []
    if isinstance(val, StdArray):
        for i, elem in enumerate(val.elements):
            r = executor(spec, elem, source, f'{path}[{i}]')
            if not r.ok:
                diags.extend(r.diagnostics)
    elif isinstance(val, StdObject):
        for f in val.fields:
            r = executor(spec, f.value, source, f'{path}.{f.name}')
            if not r.ok:
                diags.extend(r.diagnostics)
    else:
        return fail_result('constraint.each_only', {'actual': describe(val)}, source, path)
    if diags:
        return ConstraintResult(ok=False, diagnostics=diags)
    return ok_result()


def _check_in(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    choices: list[Any] = cast(list[Any], args[0]) if len(args) == 1 and isinstance(args[0], list) else args
    if any(_std_equal(val, _as_std_value(c)) for c in choices):
        return ok_result()
    return fail_result('constraint.in_not_in', {'value': describe(val), 'choices': choices}, source, path)


def _check_ip(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    s = _as_str(val)
    if s is None:
        return fail_result('constraint.string_only', {'constraint': 'ip'}, source, path)
    try:
        ipaddress.ip_address(s)
        return ok_result()
    except ValueError:
        return fail_result('constraint.invalid_value', {'what': 'IP 地址', 'value': s}, source, path)


def _check_ip4(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    s = _as_str(val)
    if s is None:
        return fail_result('constraint.string_only', {'constraint': 'ip4'}, source, path)
    try:
        ipaddress.IPv4Address(s)
        return ok_result()
    except ValueError:
        return fail_result('constraint.invalid_value', {'what': 'IPv4 地址', 'value': s}, source, path)


def _check_ip6(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    s = _as_str(val)
    if s is None:
        return fail_result('constraint.string_only', {'constraint': 'ip6'}, source, path)
    try:
        ipaddress.IPv6Address(s)
        return ok_result()
    except ValueError:
        return fail_result('constraint.invalid_value', {'what': 'IPv6 地址', 'value': s}, source, path)


def _check_regex(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    s = _as_str(val)
    if s is None:
        return fail_result('constraint.string_only', {'constraint': 'regex'}, source, path)
    pattern = str(args[0])
    try:
        if re.fullmatch(pattern, s):
            return ok_result()
        return fail_result('constraint.regex_no_match', {'value': s, 'pattern': pattern}, source, path)
    except re.error as e:
        return fail_result('constraint.regex_invalid', {'pattern': pattern, 'error': e}, source, path)


def _check_email(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    s = _as_str(val)
    if s is None:
        return fail_result('constraint.string_only', {'constraint': 'email'}, source, path)
    if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', s):
        return ok_result()
    return fail_result('constraint.invalid_value', {'what': '邮箱地址', 'value': s}, source, path)


def _check_url(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    s = _as_str(val)
    if s is None:
        return fail_result('constraint.string_only', {'constraint': 'url'}, source, path)
    p = urlparse(s)
    if p.scheme and p.netloc:
        return ok_result()
    return fail_result('constraint.invalid_value', {'what': 'URL', 'value': s}, source, path)


def _check_uuid(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    s = _as_str(val)
    if s is None:
        return fail_result('constraint.string_only', {'constraint': 'uuid'}, source, path)
    try:
        uuid.UUID(s)
        return ok_result()
    except ValueError:
        return fail_result('constraint.invalid_value', {'what': 'UUID', 'value': s}, source, path)


_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'
    r'(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$',
)


def _check_hostname(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    s = _as_str(val)
    if s is None:
        return fail_result('constraint.string_only', {'constraint': 'hostname'}, source, path)
    if _HOSTNAME_RE.fullmatch(s):
        return ok_result()
    return fail_result('constraint.invalid_value', {'what': '主机名', 'value': s}, source, path)


def _check_positive(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    num = _as_number(val)
    if num is None:
        return fail_result('constraint.numeric_only', {'constraint': 'positive'}, source, path)
    if num.is_nan():
        return fail_result('constraint.nan_not_allowed', {'constraint': 'positive'}, source, path)
    return ok_result() if num > 0 else fail_result('constraint.positive_fail', {'value': num}, source, path)


def _check_negative(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    num = _as_number(val)
    if num is None:
        return fail_result('constraint.numeric_only', {'constraint': 'negative'}, source, path)
    if num.is_nan():
        return fail_result('constraint.nan_not_allowed', {'constraint': 'negative'}, source, path)
    return ok_result() if num < 0 else fail_result('constraint.negative_fail', {'value': num}, source, path)


def _check_nonnegative(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    num = _as_number(val)
    if num is None:
        return fail_result('constraint.numeric_only', {'constraint': 'nonnegative'}, source, path)
    if num.is_nan():
        return fail_result('constraint.nan_not_allowed', {'constraint': 'nonnegative'}, source, path)
    return ok_result() if num >= 0 else fail_result('constraint.nonnegative_fail', {'value': num}, source, path)


def _check_eq(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if _std_equal(val, _as_std_value(args[0])):
        return ok_result()
    return fail_result('constraint.eq_mismatch', {'value': describe(val), 'expected': args[0]}, source, path)


def _check_unique(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if not isinstance(val, StdArray):
        return fail_result('constraint.unique_only', {}, source, path)
    for i in range(len(val.elements)):
        for j in range(i):
            if _std_equal(val.elements[i], val.elements[j]):
                return fail_result('constraint.unique_dup', {'value': describe(val.elements[i])}, source, path)
    return ok_result()
