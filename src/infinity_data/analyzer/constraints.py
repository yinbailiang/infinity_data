"""约束执行引擎 —— 类型检查与值域约束的核心。"""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any, Callable

from infinity_data.analyzer.models import Diagnostic, StdArray, StdLiteral, StdObject, StdValue
from infinity_data.tokenizer.models import SourceInfo


@dataclass
class ConstraintResult:
    """约束执行结果。"""
    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=lambda:[])
    coerced_value: StdValue | None = None  # 类型强制转换后的值（如 "80" → 80）


class ConstraintError(Exception):
    """约束违反异常（仅用于内部流控，不暴露给 API）。"""
    def __init__(self, msg: str, source: SourceInfo | None = None, path: str = "") -> None:
        self.msg = msg
        self.source = source
        self.path = path
        super().__init__(msg)


# ── 约束函数注册表 ──────────────────────────────────────


class ConstraintRegistry:
    """约束函数注册表，支持内置约束和用户自定义约束。"""

    def __init__(self) -> None:
        self._functions: dict[str, ConstraintFunc] = {}
        self._register_builtins()

    def register(self, name: str, fn: "ConstraintFunc") -> None:
        self._functions[name] = fn

    def lookup(self, name: str) -> "ConstraintFunc | None":
        return self._functions.get(name)

    def _register_builtins(self) -> None:
        for fn in _BUILTIN_CONSTRAINTS:
            self._functions[fn.name] = fn


@dataclass
class ConstraintFunc:
    """约束函数定义。"""
    name: str
    description: str
    # 执行函数：(value, source, path, args) → ConstraintResult
    execute: Callable[[StdValue | None, SourceInfo | None, str, list[Any]], ConstraintResult]
    takes_arguments: bool = False  # 是否需要参数（如 range(1,10) 需要）


# ── 内置约束实现 ─────────────────────────────────────────


def _check_type_int(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 int，实际没有值", source, path)])
    if isinstance(val, StdLiteral) and val.kind in ("int", "float"):
        if val.kind == "float":
            return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 int，实际 float({val.value})", source, path)])
        return ConstraintResult(ok=True, coerced_value=StdLiteral(kind="int", value=int(val.value)))
    return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 int，实际 {_describe(val)}", source, path)])


def _check_type_float(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 float，实际没有值", source, path)])
    if isinstance(val, StdLiteral) and val.kind in ("int", "float"):
        return ConstraintResult(ok=True, coerced_value=StdLiteral(kind="float", value=float(val.value)))
    return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 float，实际 {_describe(val)}", source, path)])


def _check_type_str(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 str，实际没有值", source, path)])
    if isinstance(val, StdLiteral) and val.kind == "str":
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 str，实际 {_describe(val)}", source, path)])


def _check_type_bool(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 bool，实际没有值", source, path)])
    if isinstance(val, StdLiteral) and val.kind in ("true", "false", "bool"):
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 bool，实际 {_describe(val)}", source, path)])


def _check_type_list(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 list，实际没有值", source, path)])
    if isinstance(val, StdArray):
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 list，实际 {_describe(val)}", source, path)])


def _check_type_dict(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 dict，实际没有值", source, path)])
    if isinstance(val, StdObject):
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 dict，实际 {_describe(val)}", source, path)])


def _check_type_exist(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    # ? 类型：值只能是 exist 或 null
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 exist 或 null，实际没有值", source, path)])
    if isinstance(val, StdLiteral) and val.kind in ("exist", "null"):
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 期望 exist 或 null，实际 {_describe(val)}", source, path)])


def _check_range(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None or not isinstance(val, StdLiteral):
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: range 约束只适用于字面量数值", source, path)])
    if len(args) < 2:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: range() 需要两个参数 (min, max)", source, path)])
    num = float(val.value) if isinstance(val.value, (int, float)) else None
    if num is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: range 约束只适用于数值", source, path)])
    lo, hi = args[0], args[1]
    if num < lo or num > hi:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(
            f"{path}: 值 {num} 不在范围 [{lo}, {hi}] 内", source, path,
        )])
    return ConstraintResult(ok=True)


def _check_in(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None or not isinstance(val, StdLiteral):
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: in 约束只适用于字面量", source, path)])
    if val.value not in args:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(
            f"{path}: 值 {val.value!r} 不在允许的值 {args!r} 中", source, path,
        )])
    return ConstraintResult(ok=True)


def _check_each(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None or not isinstance(val, StdArray):
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: each 约束只适用于数组", source, path)])
    if len(args) < 1:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: each() 需要至少一个约束参数", source, path)])
    element_constraint = args[0]  # 对每个元素应用的约束名（如 "str"）
    diags: list[Diagnostic] = []
    for i, elem in enumerate(val.elements):
        elem_result = apply_constraint_by_name(element_constraint, elem, source, f"{path}[{i}]", [])
        if not elem_result.ok:
            diags.extend(elem_result.diagnostics)
    if diags:
        return ConstraintResult(ok=False, diagnostics=diags)
    return ConstraintResult(ok=True)


def _check_ip(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None or not isinstance(val, StdLiteral) or val.kind != "str":
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: ip 约束只适用于字符串", source, path)])
    try:
        ip_address(val.value)
        return ConstraintResult(ok=True)
    except ValueError:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 无效的 IP 地址 {val.value!r}", source, path)])


def _check_size(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: size 约束需要值", source, path)])

    if isinstance(val, StdArray):
        actual = len(val.elements)
    elif isinstance(val, StdLiteral) and val.kind == "str":
        actual = len(val.value)
    else:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: size 约束只适用于字符串或数组", source, path)])

    if len(args) == 1:
        # size(exact)
        if actual != args[0]:
            return ConstraintResult(ok=False, diagnostics=[make_diagnostic(
                f"{path}: 大小 {actual} != {args[0]}", source, path,
            )])
    elif len(args) >= 2:
        lo, hi = args[0], args[1]
        if actual < lo or actual > hi:
            return ConstraintResult(ok=False, diagnostics=[make_diagnostic(
                f"{path}: 大小 {actual} 不在范围 [{lo}, {hi}] 内", source, path,
            )])

    return ConstraintResult(ok=True)


# ── 内置约束列表 ─────────────────────────────────────────


_BUILTIN_CONSTRAINTS: list[ConstraintFunc] = [
    # 类型约束
    ConstraintFunc(name="int", description="整数值", execute=_check_type_int),
    ConstraintFunc(name="float", description="浮点数值", execute=_check_type_float),
    ConstraintFunc(name="str", description="字符串值", execute=_check_type_str),
    ConstraintFunc(name="bool", description="布尔值", execute=_check_type_bool),
    ConstraintFunc(name="list", description="数组值", execute=_check_type_list),
    ConstraintFunc(name="dict", description="对象值", execute=_check_type_dict),
    ConstraintFunc(name="?", description="存在类型（exist 或 null）", execute=_check_type_exist),
    # 值域约束
    ConstraintFunc(name="range", description="数值范围 range(min, max)", execute=_check_range, takes_arguments=True),
    ConstraintFunc(name="in", description="枚举值 in(v1, v2, ...)", execute=_check_in, takes_arguments=True),
    ConstraintFunc(name="each", description="数组元素约束 each(type)", execute=_check_each, takes_arguments=True),
    ConstraintFunc(name="ip", description="IP 地址格式", execute=_check_ip),
    ConstraintFunc(name="size", description="大小约束 size(exact) 或 size(min, max)", execute=_check_size, takes_arguments=True),
]


# ── 辅助函数 ─────────────────────────────────────────────


def apply_constraint_by_name(
    name: str, val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """根据约束名查找并执行约束函数。"""
    # 使用默认注册表查找
    registry = ConstraintRegistry()
    func = registry.lookup(name)
    if func is None:
        return ConstraintResult(ok=False, diagnostics=[make_diagnostic(f"{path}: 未知约束函数 {name!r}", source, path)])
    return func.execute(val, source, path, args)


def make_diagnostic(msg: str, source: SourceInfo | None = None, path: str = "") -> Diagnostic:
    return Diagnostic(level="error", message=msg, source=source, path=path)


def _describe(val: StdValue | None) -> str:
    """值的可读描述。"""
    if val is None:
        return "无值"
    if isinstance(val, StdLiteral):
        return f"{val.kind}({val.value!r})"
    if isinstance(val, StdArray):
        return f"array[{len(val.elements)}]"
    # 经以上排除后 val 必为 StdObject
    return f"object[{len(val.fields)}]"
