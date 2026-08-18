"""约束注册表与约束执行引擎。

设计要点：

- 表驱动：每个约束登记 ``(name, fn, min_args, max_args, description)``
- 约束函数签名统一：``fn(value, source, path, args, executor)``
- ``executor`` 回调支持嵌套约束：``each`` / ``not`` / ``any`` / ``one`` /
  ``all`` / ``when`` / ``field`` / 模板约束
- M5 将在 :class:`ConstraintEntry` 上追加 json_schema 生成回调，
  实现「模板即约束 → JSON Schema」的单注册表复用
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Protocol, cast
from urllib.parse import urlparse

from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.semantic.models import (
    StdArray,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.tokenizer.models.raw_tokens import SourceRange

# ═══════════════════════════════════════════════════════════
# 基础类型
# ═══════════════════════════════════════════════════════════


@dataclass
class ResolvedConstraint:
    """已解析的约束。嵌套参数为 Python 值或 ResolvedConstraint。"""

    name: str
    args: list[Any] = field(default_factory=list[Any])
    source: SourceRange | None = None


@dataclass
class ConstraintResult:
    """约束执行结果。"""

    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])
    coerced_value: StdValue | None = None  # 类型强制转换后的值


class Executor(Protocol):
    """嵌套约束执行回调（由 SemanticAnalyzer 提供）。"""

    def __call__(
        self,
        constraint: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult: ...


ConstraintFn = Callable[
    [StdValue | None, SourceRange | None, str, list[Any], Executor],
    ConstraintResult,
]


@dataclass
class ConstraintEntry:
    """约束登记项。"""

    name: str
    fn: ConstraintFn
    min_args: int = 0
    max_args: int | None = None
    description: str = ''


def ok_result(coerced: StdValue | None = None) -> ConstraintResult:
    """构造通过结果。"""
    return ConstraintResult(ok=True, coerced_value=coerced)


def fail_result(
    code: str,
    params: Mapping[str, Any],
    source: SourceRange | None,
    path: str,
) -> ConstraintResult:
    """构造结构化失败结果（code + params，message 由注册表渲染）。"""
    return ConstraintResult(
        ok=False,
        diagnostics=[
            Diagnostic(severity=Severity.ERROR, code=code, params=dict(params), source=source, path=path),
        ],
    )


def describe(val: StdValue | None) -> str:
    """人类可读的值描述。"""
    if val is None:
        return '无值'
    if isinstance(val, StdLiteral):
        return f'{val.kind}({val.value!r})'
    if isinstance(val, StdArray):
        return f'list[{len(val.elements)}]'
    return f'dict[{len(val.fields)}]'


def _as_number(val: StdValue | None) -> Decimal | None:
    """字面量 → 数值（int/float kind 才有效）。"""
    if isinstance(val, StdLiteral) and val.kind in ('int', 'float'):
        v = val.value
        if isinstance(v, int):
            return Decimal(v)
        if isinstance(v, Decimal):
            return v
    return None


def _as_str(val: StdValue | None) -> str | None:
    """字面量 → 字符串（str kind 才有效）。"""
    if isinstance(val, StdLiteral) and val.kind == 'str':
        v = val.value
        return v if isinstance(v, str) else None
    return None


def _as_decimal_arg(a: Any) -> Decimal | None:
    """约束参数 → Decimal（int / Decimal 才有效；NaN 视为无效参数）。"""
    if isinstance(a, bool):
        return None
    if isinstance(a, int):
        return Decimal(a)
    if isinstance(a, Decimal):
        # Decimal 比较遇 NaN 会抛 InvalidOperation（默认 trap），此处拒绝 NaN 参数
        return None if a.is_nan() else a
    return None


def _safe_equal(a: Any, b: Any) -> bool:
    """安全相等比较：Decimal NaN 参与比较会抛 InvalidOperation，视为不相等。"""
    try:
        return bool(a == b)
    except InvalidOperation:
        return False


def _std_equal(a: StdValue | None, b: StdValue | None) -> bool:
    """StdValue 结构相等（直接工作在 Std 节点上，不经 Python 降维）。

    语义：
    - 字面量：kind 相同且值相等；int/float 数值交叉相等（eq(42) 对 float 42 成立）
    - bool 与 int 不相等（避免 Python ``True == 1`` 陷阱）
    - NaN 与任何值不相等（IEEE 754）
    - 数组：等长且逐元素相等
    - 对象：等字段集且逐字段值相等（与字段顺序无关）
    """
    if a is None or b is None:
        return a is b
    if isinstance(a, StdLiteral) and isinstance(b, StdLiteral):
        if a.kind == b.kind:
            return _safe_equal(a.value, b.value)
        if {a.kind, b.kind} == {'int', 'float'}:
            na = _as_number(a)
            nb = _as_number(b)
            if na is not None and nb is not None:
                return _safe_equal(na, nb)
        return False
    if isinstance(a, StdArray) and isinstance(b, StdArray):
        if len(a.elements) != len(b.elements):
            return False
        return all(_std_equal(x, y) for x, y in zip(a.elements, b.elements))
    if isinstance(a, StdObject) and isinstance(b, StdObject):
        if len(a.fields) != len(b.fields):
            return False
        for f in a.fields:
            other = b.get(f.name)
            if other is None or not _std_equal(f.value, other.value):
                return False
        return True
    return False


def _as_std_value(v: Any) -> StdValue:
    """约束参数（Python 值）→ StdValue（与值同构后比较）。"""
    if v is None:
        return StdLiteral(kind='null', value=None)
    if isinstance(v, bool):
        return StdLiteral(kind='bool', value=v)
    if isinstance(v, int):
        return StdLiteral(kind='int', value=v)
    if isinstance(v, Decimal):
        return StdLiteral(kind='float', value=v)
    if isinstance(v, str):
        return StdLiteral(kind='str', value=v)
    if isinstance(v, (list, tuple)):
        items = cast(list[Any], v)
        return StdArray(elements=[_as_std_value(e) for e in items])
    if isinstance(v, dict):
        mapping = cast(dict[Any, Any], v)
        return StdObject(fields=[StdField(name=str(k), value=_as_std_value(e)) for k, e in mapping.items()])
    return StdLiteral(kind='str', value=str(v))


def _as_spec(arg: Any) -> ResolvedConstraint | None:
    """嵌套参数 → 约束规格（ResolvedConstraint 或裸名字符串）。"""
    if isinstance(arg, ResolvedConstraint):
        return arg
    if isinstance(arg, str):
        return ResolvedConstraint(name=arg)
    return None


def _spec_name(arg: Any) -> str:
    """取参数的约束名（has/field 的第一个参数是裸名字）。"""
    if isinstance(arg, ResolvedConstraint):
        return arg.name
    return str(arg)


# ═══════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════


class ConstraintRegistry:
    """约束注册表：内置约束 + 用户自定义（模板即约束）。"""

    def __init__(self) -> None:
        self._entries: dict[str, ConstraintEntry] = {}
        self._register_builtins()

    def register(
        self,
        name: str,
        fn: ConstraintFn,
        *,
        min_args: int = 0,
        max_args: int | None = None,
        description: str = '',
    ) -> None:
        self._entries[name] = ConstraintEntry(
            name=name,
            fn=fn,
            min_args=min_args,
            max_args=max_args,
            description=description,
        )

    def lookup(self, name: str) -> ConstraintEntry | None:
        return self._entries.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._entries)

    def apply(
        self,
        constraint: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
        executor: Executor,
    ) -> ConstraintResult:
        """按名称执行约束（含参数个数校验）。"""
        entry = self._entries.get(constraint.name)
        if entry is None:
            return fail_result('constraint.unknown', {'name': constraint.name}, source, path)
        n = len(constraint.args)
        if n < entry.min_args or (entry.max_args is not None and n > entry.max_args):
            expected = str(entry.min_args) if entry.max_args is None else f'{entry.min_args}~{entry.max_args}'
            return fail_result('constraint.arg_count', {'name': constraint.name, 'expected': expected, 'given': n}, source, path)
        return entry.fn(value, source, path, constraint.args, executor)

    def _register_builtins(self) -> None:
        """注册 neo_desg.md §1.2 全部内置约束。"""
        # ── 类型约束 ──────────────────────────────
        self.register('object', _check_object, description='通用超类型，总是通过')
        self.register('?', _check_nullable, description='纯可空类型：noexist 或 null')
        self.register('int', _check_int, description='有符号整数')
        self.register('float', _check_float, description='十进制浮点（int 自动提升）')
        self.register('str', _check_str, description='utf-8 字符串')
        self.register('bool', _check_bool, description='布尔值')
        self.register('list', _check_list, description='数组')
        self.register('dict', _check_dict, description='字典')

        # ── 一般约束 ──────────────────────────────
        self.register('range', _check_range, min_args=1, max_args=2, description='数值范围 range(ge[, le])，可省略一端')
        self.register('size', _check_size, min_args=1, max_args=2, description='集合大小或字符串长度 size(ge[, le])')
        self.register('each', _check_each, min_args=1, max_args=1, description='每个元素均满足 each(constraint)')
        self.register('in', _check_in, min_args=1, description='值在给定选项中 in(choice, ...)')
        self.register('ip', _check_ip, description='IPv4 或 IPv6 地址')
        self.register('ip4', _check_ip4, description='IPv4 地址')
        self.register('ip6', _check_ip6, description='IPv6 地址')
        self.register('regex', _check_regex, min_args=1, max_args=1, description='正则全匹配 regex("re")')
        self.register('email', _check_email, description='邮箱格式')
        self.register('url', _check_url, description='URL 格式')
        self.register('uuid', _check_uuid, description='UUID 格式')
        self.register('hostname', _check_hostname, description='主机名格式')
        self.register('positive', _check_positive, description='正数 (> 0)')
        self.register('negative', _check_negative, description='负数 (< 0)')
        self.register('nonnegative', _check_nonnegative, description='非负数 (>= 0)')
        self.register('eq', _check_eq, min_args=1, max_args=1, description='等于指定值 eq(value)')
        self.register('unique', _check_unique, description='集合元素不重复')

        # ── 字典约束 ──────────────────────────────
        self.register('has', _check_has, min_args=1, max_args=1, description='包含指定键 has(key)')
        self.register('field', _check_field, min_args=2, max_args=2, description='字段约束 field(name, constraint)')

        # ── 逻辑约束 ──────────────────────────────
        self.register('not', _check_not, min_args=1, max_args=1, description='内部约束不满足则满足')
        self.register('any', _check_any, min_args=1, description='任意子约束满足')
        self.register('one', _check_one, min_args=1, description='恰好一个子约束满足')
        self.register('all', _check_all, min_args=1, description='全部子约束满足')
        self.register(
            'when', _check_when, min_args=2, max_args=2, description='条件满足时要求另一约束满足 when(cond, req)'
        )


# ═══════════════════════════════════════════════════════════
# 类型约束
# ═══════════════════════════════════════════════════════════


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
    return fail_result('constraint.type_mismatch', {'expected': 'noexist 或 null', 'actual': describe(val)}, source, path)


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
    if isinstance(val, StdLiteral) and val.kind == 'int':
        v = val.value
        if isinstance(v, int):
            return ok_result(StdLiteral(kind='float', value=Decimal(v)))
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


# ═══════════════════════════════════════════════════════════
# 一般约束
# ═══════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════
# 字典约束
# ═══════════════════════════════════════════════════════════


def _check_has(
    val: StdValue | None,
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
    val: StdValue | None,
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


# ═══════════════════════════════════════════════════════════
# 逻辑约束
# ═══════════════════════════════════════════════════════════


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
