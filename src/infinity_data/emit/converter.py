"""降维器：StdAst → 纯 Python 值（dict / list / 标量）。

- ``noexist`` 字段不出现在输出中
- ``null`` 字段保留键（值为 None），``keep_null=False`` 时跳过
- 浮点保持 :class:`decimal.Decimal`（无限精度）；NaN / ±Infinity 以 Decimal 表示，
  JSON/YAML 序列化时的特殊编码由 M4 转换层负责
"""

from __future__ import annotations

from typing import Any

from infinity_data.semantic.models import StdArray, StdLiteral, StdObject, StdValue


def reduce_object(obj: StdObject, *, keep_null: bool = True) -> dict[str, Any]:
    """将 StdObject 降维为 Python dict。"""
    result: dict[str, Any] = {}
    for f in obj.fields:
        if f.value is None or f.is_noexist:
            continue
        if f.is_null:
            if keep_null:
                result[f.name] = None
            continue
        result[f.name] = reduce_value(f.value, keep_null=keep_null)
    return result


def reduce_array(arr: StdArray, *, keep_null: bool = True) -> list[Any]:
    """将 StdArray 降维为 Python list。"""
    return [reduce_value(v, keep_null=keep_null) for v in arr.elements]


def reduce_value(val: StdValue, *, keep_null: bool = True) -> Any:
    """将任意 StdValue 降维为 Python 原生值。"""
    match val:
        case StdLiteral():
            return _reduce_literal(val)
        case StdArray():
            return reduce_array(val, keep_null=keep_null)
        case StdObject():
            return reduce_object(val, keep_null=keep_null)
    raise TypeError(f'未知 StdValue 类型: {type(val)}')


# ── 内部 ────────────────────────────────────────────────


def _reduce_literal(lit: StdLiteral) -> Any:
    match lit.kind:
        case 'null' | 'noexist':
            return None
        case _:
            return lit.value
