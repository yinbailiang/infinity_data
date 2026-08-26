"""约束核心类型与共享辅助（注册表包的内部基础层）。

- 执行结果 / 嵌套回调协议 / 登记项
- 人类可读描述与数值、嵌套参数辅助
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Protocol, cast

from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.semantic.builder.models import (
    ResolvedConstraint,
    StdArray,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.tokenizer.models.raw_tokens import SourceRange

if TYPE_CHECKING:
    from infinity_data.sandbox import Sandbox

# ═══════════════════════════════════════════════════════════
# 基础类型
# ═══════════════════════════════════════════════════════════


@dataclass
class ConstraintResult:
    """约束执行结果（只校验，不转换值）。"""

    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])


class Executor(Protocol):
    """嵌套约束执行回调（由 ConstraintExecutor 提供）。

    ``sandbox``：文件系统依赖约束（``exist`` / ``dir`` / ``file`` / ``link``）经此
    授权探测（零信任 deny_all 下拒绝 → ``constraint.path_denied``）。
    """

    def __call__(
        self,
        constraint: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult: ...

    @property
    def sandbox(self) -> Sandbox: ...


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


def ok_result() -> ConstraintResult:
    """构造通过结果。"""
    return ConstraintResult(ok=True)


def fail_result(
    code: str,
    params: Mapping[str, Any],
    source: SourceRange | None,
    path: str,
    *,
    severity: Severity = Severity.ERROR,
) -> ConstraintResult:
    """构造结构化失败结果（code + params，message 由注册表渲染）。

    ``severity``：默认 ERROR；沙盒越界等「软失败」可传 WARNING（仍 ``ok=False``，
    约束不满足，但诊断级别为警告）。
    """
    return ConstraintResult(
        ok=False,
        diagnostics=[
            Diagnostic(severity=severity, code=code, params=dict(params), source=source, path=path),
        ],
    )


# ═══════════════════════════════════════════════════════════
# 共享辅助
# ═══════════════════════════════════════════════════════════


def describe(val: StdValue | None) -> str:
    """人类可读的值描述。"""
    if val is None:
        return '无值'
    if isinstance(val, StdLiteral):
        return f'{val.kind}({val.value!r})'
    if isinstance(val, StdArray):
        return f'list[{len(val.elements)}]'
    return f'dict[{len(val.fields)}]'


def as_number(val: StdValue | None) -> Decimal | None:
    """字面量 → 数值（int/float kind 才有效）。"""
    if isinstance(val, StdLiteral) and val.kind in ('int', 'float'):
        v = val.value
        if isinstance(v, int):
            return Decimal(v)
        if isinstance(v, Decimal):
            return v
    return None


def as_str(val: StdValue | None) -> str | None:
    """字面量 → 字符串（str / path kind 才有效；path 取 POSIX 形式）。"""
    if isinstance(val, StdLiteral) and val.kind in ('str', 'path'):
        v = val.value
        if val.kind == 'path':
            from pathlib import PurePath

            return v.as_posix() if isinstance(v, PurePath) else str(v)
        return v if isinstance(v, str) else None
    return None


def as_decimal_arg(a: Any) -> Decimal | None:
    """约束参数 → Decimal（int / Decimal 才有效；NaN 视为无效参数）。"""
    if isinstance(a, bool):
        return None
    if isinstance(a, int):
        return Decimal(a)
    if isinstance(a, Decimal):
        # Decimal 比较遇 NaN 会抛 InvalidOperation（默认 trap），此处拒绝 NaN 参数
        return None if a.is_nan() else a
    return None


def safe_equal(a: Any, b: Any) -> bool:
    """安全相等比较：Decimal NaN 参与比较会抛 InvalidOperation，视为不相等。"""
    try:
        return bool(a == b)
    except InvalidOperation:
        return False


def std_equal(a: StdValue | None, b: StdValue | None) -> bool:
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
            return safe_equal(a.value, b.value)
        if {a.kind, b.kind} == {'int', 'float'}:
            na = as_number(a)
            nb = as_number(b)
            if na is not None and nb is not None:
                return safe_equal(na, nb)
        # path ↔ str 交叉相等：路径值与其 POSIX 字符串形式等价（§1.5）
        if {a.kind, b.kind} == {'path', 'str'}:
            sa = as_str(a)
            sb = as_str(b)
            return sa is not None and sb is not None and safe_equal(sa, sb)
        return False
    if isinstance(a, StdArray) and isinstance(b, StdArray):
        if len(a.elements) != len(b.elements):
            return False
        return all(std_equal(x, y) for x, y in zip(a.elements, b.elements))
    if isinstance(a, StdObject) and isinstance(b, StdObject):
        if len(a.fields) != len(b.fields):
            return False
        for f in a.fields:
            other = b.get(f.name)
            if other is None or not std_equal(f.value, other.value):
                return False
        return True
    return False


def as_std_value(v: Any) -> StdValue:
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
        return StdArray(elements=[as_std_value(e) for e in items])
    if isinstance(v, dict):
        mapping = cast(dict[Any, Any], v)
        return StdObject(fields=[StdField(name=str(k), value=as_std_value(e)) for k, e in mapping.items()])
    return StdLiteral(kind='str', value=str(v))


def as_spec(arg: Any) -> ResolvedConstraint | None:
    """嵌套参数 → 约束规格（ResolvedConstraint 或裸名字符串）。"""
    if isinstance(arg, ResolvedConstraint):
        return arg
    if isinstance(arg, str):
        return ResolvedConstraint(name=arg)  # pyright: ignore[reportCallIssue]
    return None


def spec_name(arg: Any) -> str:
    """取参数的约束名（has/field 的第一个参数是裸名字）。"""
    if isinstance(arg, ResolvedConstraint):
        return arg.name
    return str(arg)
