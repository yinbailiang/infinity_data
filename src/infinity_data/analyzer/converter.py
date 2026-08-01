"""降维器：StandardAst → 纯 Python dict / list。

将携带类型、约束、来源信息的标准 AST 降维为纯数据，
可用于序列化为 JSON / YAML / Nix 表达式等目标格式。
"""

from __future__ import annotations

from typing import Any

from infinity_data.analyzer.models import StdArray, StdLiteral, StdObject, StdValue


EXIST_MARKER = {"__exist__": True}
"""exist 字段降维时的标记值。"""


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
                case "exist":
                    return dict(EXIST_MARKER)  # {"__exist__": true}
                case _:
                    return v
        case StdObject():
            return reduce_to_dict(val, keep_null=keep_null)
        case StdArray():
            return reduce_to_list(val, keep_null=keep_null)
    return None
