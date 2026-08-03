"""约束执行引擎 —— 类型检查与值域约束的核心。

基于 neo_desg.md 重新设计，新增：
- 逻辑约束: not(), any(), one(), all()
- ip4, ip6 约束
- regex() 约束
- size() 约束
- object 通用超类型
- 三态可空: noexist / null / value
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Any, Callable

from infinity_data.analyzer.models import Diagnostic, StdArray, StdLiteral, StdObject, StdValue
from infinity_data.tokenizer.models import SourceInfo


# ═══════════════════════════════════════════════════════════
# 约束结果
# ═══════════════════════════════════════════════════════════

@dataclass
class ConstraintResult:
    """约束执行结果。"""
    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=lambda: [])
    coerced_value: StdValue | None = None  # 类型强制转换后的值


class ConstraintError(Exception):
    """约束违反异常。"""
    def __init__(self, msg: str, source: SourceInfo | None = None, path: str = "") -> None:
        self.msg = msg
        self.source = source
        self.path = path
        super().__init__(msg)


# ═══════════════════════════════════════════════════════════
# 约束函数类型
# ═══════════════════════════════════════════════════════════

ConstraintFuncCallable = Callable[
    [StdValue | None, SourceInfo | None, str, list[Any]],
    ConstraintResult,
]


# ═══════════════════════════════════════════════════════════
# 约束注册表
# ═══════════════════════════════════════════════════════════

class ConstraintRegistry:
    """约束函数注册表，支持内置约束和用户自定义约束（模板约束）。"""

    def __init__(self) -> None:
        self._functions: dict[str, ConstraintFuncCallable] = {}
        self._register_builtins()

    def register(self, name: str, fn: ConstraintFuncCallable) -> None:
        self._functions[name] = fn

    def lookup(self, name: str) -> ConstraintFuncCallable | None:
        return self._functions.get(name)

    def _register_builtins(self) -> None:
        builtins: list[tuple[str, ConstraintFuncCallable]] = [
            # ── 类型约束 ──────────────────────
            ("object", _check_type_object),
            ("int", _check_type_int),
            ("float", _check_type_float),
            ("str", _check_type_str),
            ("bool", _check_type_bool),
            ("list", _check_type_list),
            ("dict", _check_type_dict),
            ("?", _check_type_nullable),
            # ── 一般约束 ──────────────────────
            ("range", _check_range),
            ("size", _check_size),
            ("each", _check_each),
            ("in", _check_in),
            ("ip", _check_ip),
            ("ip4", _check_ip4),
            ("ip6", _check_ip6),
            ("regex", _check_regex),
            # ── 逻辑约束 ──────────────────────
            ("not", _check_not),
            ("any", _check_any),
            ("one", _check_one),
            ("all", _check_all),
        ]
        for name, fn in builtins:
            self._functions[name] = fn


# ═══════════════════════════════════════════════════════════
# 诊断辅助
# ═══════════════════════════════════════════════════════════

def make_diagnostic(msg: str, source: SourceInfo | None, path: str = "", level: str = "error") -> Diagnostic:
    return Diagnostic(level=level, message=msg, source=source, path=path)


# ═══════════════════════════════════════════════════════════
# apply_constraint_by_name
# ═══════════════════════════════════════════════════════════

# 默认全局注册表
_default_registry: ConstraintRegistry | None = None


def _get_default_registry() -> ConstraintRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ConstraintRegistry()
    return _default_registry


def apply_constraint_by_name(
    name: str,
    value: StdValue | None,
    source: SourceInfo | None,
    path: str,
    args: list[Any],
) -> ConstraintResult:
    """按名称执行约束。"""
    registry = _get_default_registry()

    # 首先检查注册表中的内置约束
    fn = registry.lookup(name)
    if fn is not None:
        return fn(value, source, path, args)

    # 如果不是内置约束，可能是模板约束（由 SemanticAnalyzer 处理）
    # 返回 ok=True，让 SemanticAnalyzer 中的模板约束逻辑接管
    return ConstraintResult(ok=True)


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════

def _describe(val: StdValue | None) -> str:
    """人类可读的值描述。"""
    if val is None:
        return "无值"
    if isinstance(val, StdLiteral):
        return f"{val.kind}({val.value!r})"
    if isinstance(val, StdArray):
        return f"array[{len(val.elements)}]"
    if isinstance(val, StdObject):
        return f"object{{{len(val.fields)} fields}}"
    return type(val).__name__


# ═══════════════════════════════════════════════════════════
# 类型约束实现
# ═══════════════════════════════════════════════════════════

def _check_type_object(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """object: 所有类型都是 object，总是通过。"""
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 期望 object，实际没有值", source, path),
        ])
    return ConstraintResult(ok=True)


def _check_type_int(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 期望 int，实际没有值", source, path),
        ])
    if isinstance(val, StdLiteral) and val.kind in ("int", "float"):
        if val.kind == "float":
            return ConstraintResult(ok=False, diagnostics=[
                make_diagnostic(f"{path}: 期望 int，实际 float({val.value})", source, path),
            ])
        return ConstraintResult(ok=True, coerced_value=StdLiteral(kind="int", value=int(val.value)))
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: 期望 int，实际 {_describe(val)}", source, path),
    ])


def _check_type_float(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 期望 float，实际没有值", source, path),
        ])
    if isinstance(val, StdLiteral) and val.kind in ("int", "float"):
        return ConstraintResult(ok=True, coerced_value=StdLiteral(kind="float", value=float(val.value)))
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: 期望 float，实际 {_describe(val)}", source, path),
    ])


def _check_type_str(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 期望 str，实际没有值", source, path),
        ])
    if isinstance(val, StdLiteral) and val.kind in ("str", "mlstr"):
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: 期望 str，实际 {_describe(val)}", source, path),
    ])


def _check_type_bool(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 期望 bool，实际没有值", source, path),
        ])
    if isinstance(val, StdLiteral) and val.kind in ("true", "false", "bool"):
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: 期望 bool，实际 {_describe(val)}", source, path),
    ])


def _check_type_list(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 期望 list，实际没有值", source, path),
        ])
    if isinstance(val, StdArray):
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: 期望 list，实际 {_describe(val)}", source, path),
    ])


def _check_type_dict(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 期望 dict，实际没有值", source, path),
        ])
    if isinstance(val, StdObject):
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: 期望 dict，实际 {_describe(val)}", source, path),
    ])


def _check_type_nullable(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """? 类型: 值只能是 noexist 或 null。"""
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 期望 noexist 或 null，实际没有值", source, path),
        ])
    if isinstance(val, StdLiteral) and val.kind in ("noexist", "null"):
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: 期望 noexist 或 null，实际 {_describe(val)}", source, path),
    ])


# ═══════════════════════════════════════════════════════════
# 一般约束实现
# ═══════════════════════════════════════════════════════════

def _check_range(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    if val is None or not isinstance(val, StdLiteral):
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: range 约束只适用于字面量数值", source, path),
        ])
    if len(args) < 2:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: range() 需要两个参数 (ge, le)", source, path),
        ])
    num = float(val.value) if isinstance(val.value, (int, float)) else None
    if num is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: range 约束只适用于数值", source, path),
        ])
    lo, hi = float(args[0]), float(args[1])
    if num < lo or num > hi:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 值 {num} 不在范围 [{lo}, {hi}] 内", source, path),
        ])
    return ConstraintResult(ok=True)


def _check_size(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """size(ge, le): 检查字符串长度或数组/对象大小。"""
    if val is None:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: size 约束需要值", source, path),
        ])
    if len(args) < 2:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: size() 需要两个参数 (ge, le)", source, path),
        ])

    size_val: int | None = None
    if isinstance(val, StdLiteral) and val.kind in ("str", "mlstr"):
        size_val = len(str(val.value))
    elif isinstance(val, StdArray):
        size_val = len(val.elements)
    elif isinstance(val, StdObject):
        size_val = len(val.fields)
    else:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: size 约束适用于 str/list/dict", source, path),
        ])

    lo, hi = int(args[0]), int(args[1])
    if size_val < lo or size_val > hi:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 大小 {size_val} 不在范围 [{lo}, {hi}] 内", source, path),
        ])
    return ConstraintResult(ok=True)


def _check_in(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """in(choice1, choice2, ...): 值必须在给定选项中。"""
    if val is None or not isinstance(val, StdLiteral):
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: in 约束只适用于字面量", source, path),
        ])
    if val.value not in args:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 值 {val.value!r} 不在允许的值 {args!r} 中", source, path),
        ])
    return ConstraintResult(ok=True)


def _check_each(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """each(constraint): 对数组每个元素应用约束。"""
    if val is None or not isinstance(val, StdArray):
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: each 约束只适用于数组", source, path),
        ])
    if len(args) < 1:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: each() 需要至少一个约束参数", source, path),
        ])
    element_constraint = args[0]  # 约束名（如 "str"）
    diags: list[Diagnostic] = []
    for i, elem in enumerate(val.elements):
        elem_result = apply_constraint_by_name(str(element_constraint), elem, source, f"{path}[{i}]", [])
        if not elem_result.ok:
            diags.extend(elem_result.diagnostics)
    if diags:
        return ConstraintResult(ok=False, diagnostics=diags)
    return ConstraintResult(ok=True)


def _check_ip(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """ip: 必须是合法的 IPv4 或 IPv6 地址。"""
    if val is None or not isinstance(val, StdLiteral) or val.kind not in ("str", "mlstr"):
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: ip 约束只适用于字符串", source, path),
        ])
    try:
        ip_address(str(val.value))
        return ConstraintResult(ok=True)
    except ValueError:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 无效的 IP 地址 {val.value!r}", source, path),
        ])


def _check_ip4(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """ip4: 必须是合法的 IPv4 地址。"""
    if val is None or not isinstance(val, StdLiteral) or val.kind not in ("str", "mlstr"):
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: ip4 约束只适用于字符串", source, path),
        ])
    try:
        IPv4Address(str(val.value))
        return ConstraintResult(ok=True)
    except ValueError:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 无效的 IPv4 地址 {val.value!r}", source, path),
        ])


def _check_ip6(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """ip6: 必须是合法的 IPv6 地址。"""
    if val is None or not isinstance(val, StdLiteral) or val.kind not in ("str", "mlstr"):
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: ip6 约束只适用于字符串", source, path),
        ])
    try:
        IPv6Address(str(val.value))
        return ConstraintResult(ok=True)
    except ValueError:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 无效的 IPv6 地址 {val.value!r}", source, path),
        ])


def _check_regex(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """regex("pattern"): 字符串必须匹配正则表达式。"""
    if val is None or not isinstance(val, StdLiteral) or val.kind not in ("str", "mlstr"):
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: regex 约束只适用于字符串", source, path),
        ])
    if len(args) < 1:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: regex() 需要一个正则表达式参数", source, path),
        ])
    pattern = str(args[0])
    try:
        if re.match(pattern, str(val.value)):
            return ConstraintResult(ok=True)
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 值 {val.value!r} 不匹配正则 {pattern!r}", source, path),
        ])
    except re.error as e:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: 无效的正则表达式 {pattern!r}: {e}", source, path),
        ])


# ═══════════════════════════════════════════════════════════
# 逻辑约束实现
# ═══════════════════════════════════════════════════════════

def _check_not(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """not(constraint): 内部约束不满足则满足。"""
    if len(args) < 1:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: not() 需要一个约束参数", source, path),
        ])
    inner_result = apply_constraint_by_name(str(args[0]), val, source, path, [])
    if not inner_result.ok:
        return ConstraintResult(ok=True)  # 内部不满足 → not 满足
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: not 约束失败（内部约束意外满足）", source, path),
    ])


def _check_any(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """any(c1, c2, ...): 内部约束有任意多个被满足则满足。"""
    if len(args) < 1:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: any() 需要至少一个约束参数", source, path),
        ])
    diags: list[Diagnostic] = []
    for arg in args:
        inner_result = apply_constraint_by_name(str(arg), val, source, path, [])
        if inner_result.ok:
            return ConstraintResult(ok=True)
        diags.extend(inner_result.diagnostics)
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: any 约束失败（所有子约束都不满足）", source, path),
        *diags,
    ])


def _check_one(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """one(c1, c2, ...): 内部约束只有一个被满足则满足。"""
    if len(args) < 1:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: one() 需要至少一个约束参数", source, path),
        ])
    satisfied: list[str] = []
    diags: list[Diagnostic] = []
    for arg in args:
        inner_result = apply_constraint_by_name(str(arg), val, source, path, [])
        if inner_result.ok:
            satisfied.append(str(arg))
        else:
            diags.extend(inner_result.diagnostics)
    if len(satisfied) == 1:
        return ConstraintResult(ok=True)
    if len(satisfied) == 0:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: one 约束失败（没有子约束被满足）", source, path),
            *diags,
        ])
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: one 约束失败（{len(satisfied)} 个子约束被满足: {satisfied}）", source, path),
    ])


def _check_all(
    val: StdValue | None, source: SourceInfo | None, path: str, args: list[Any],
) -> ConstraintResult:
    """all(c1, c2, ...): 内部约束全部满足则满足。"""
    if len(args) < 1:
        return ConstraintResult(ok=False, diagnostics=[
            make_diagnostic(f"{path}: all() 需要至少一个约束参数", source, path),
        ])
    diags: list[Diagnostic] = []
    for arg in args:
        inner_result = apply_constraint_by_name(str(arg), val, source, path, [])
        if not inner_result.ok:
            diags.extend(inner_result.diagnostics)
    if not diags:
        return ConstraintResult(ok=True)
    return ConstraintResult(ok=False, diagnostics=[
        make_diagnostic(f"{path}: all 约束失败", source, path),
        *diags,
    ])
