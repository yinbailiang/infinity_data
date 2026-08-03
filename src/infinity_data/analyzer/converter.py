"""降维器：StandardAst → 纯 Python dict / list。

基于 neo_desg.md 重新设计：
- noexist 字段不出现在输出中
- nan, +inf, -inf 正确处理
- null 字段保留键（值为 None）
"""

from __future__ import annotations

import math
from typing import Any

from infinity_data.analyzer.models import StdArray, StdLiteral, StdObject, StdValue


def reduce_to_dict(obj: StdObject, *, keep_null: bool = True) -> dict[str, Any]:
    """将 StdObject 降维为 Python dict。

    Args:
        obj: 标准对象
        keep_null: 是否保留值为 null 的字段。默认 True（保留键，值为 None）。
    """
    result: dict[str, Any] = {}
    for field in obj.fields:
        if field.value is None:
            continue

        # noexist 字段：不出现在结果中
        if isinstance(field.value, StdLiteral) and field.value.kind == "noexist":
            continue

        # null 字段：默认保留键（值为 None），keep_null=False 时跳过
        if isinstance(field.value, StdLiteral) and field.value.kind == "null":
            if keep_null:
                result[field.name] = None
            continue

        result[field.name] = _reduce_value(field.value, keep_null=keep_null)

    return result


def reduce_to_list(arr: StdArray, *, keep_null: bool = True) -> list[Any]:
    """将 StdArray 降维为 Python list。"""
    return [
        _reduce_value(v, keep_null=keep_null)
        for v in arr.elements
    ]


def reduce_value(val: StdValue, *, keep_null: bool = True) -> Any:
    """将任意 StdValue 降维为 Python 原生类型。"""
    return _reduce_value(val, keep_null=keep_null)


# ── 内部 ────────────────────────────────────────────────

def _reduce_value(val: StdValue, *, keep_null: bool) -> Any:
    match val:
        case StdLiteral(kind=k, value=v):
            match k:
                case "str" | "int" | "float" | "bool":
                    return v
                case "null":
                    return None
                case "noexist":
                    return None  # 不应到达这里（在 reduce_to_dict 中已过滤）
                case "nan":
                    return float("nan")
                case "+inf":
                    return float("inf")
                case "-inf":
                    return float("-inf")
                case _:
                    return v
        case StdObject():
            return reduce_to_dict(val, keep_null=keep_null)
        case StdArray():
            return reduce_to_list(val, keep_null=keep_null)
    return None

