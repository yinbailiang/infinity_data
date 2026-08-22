"""JSON path 统一实现：操作 StdValue 树（§4.4，含首段下标）。

``!file`` 外部导入与 ``!var`` 本地注入共用同一套 path 语义——统一处理流程：
外部数据先转 AST（:func:`python_to_std`），再经本函数投影；
``!var`` 求值结果本就是 StdValue，直接投影。
"""

from __future__ import annotations

from infinity_data.parser import JsonPathIndex, JsonPathKey
from infinity_data.semantic.std import StdArray, StdObject, StdValue


def apply_json_path(value: StdValue, segments: list[JsonPathKey | JsonPathIndex]) -> StdValue:
    """按 JSON path 在 StdValue 树上定位；失败抛 KeyError / IndexError / TypeError。

    - ``JsonPathKey`` → 在 :class:`StdObject` 取字段（缺失抛 ``KeyError``）
    - ``JsonPathIndex`` → 在 :class:`StdArray` 取下标（越界抛 ``IndexError``）
    - 段与节点类型不匹配 → 抛 ``TypeError``
    """
    current = value
    for seg in segments:
        if isinstance(seg, JsonPathKey):
            if not isinstance(current, StdObject):
                raise TypeError('path 段需要 dict')
            f = next((f for f in current.fields if f.name == seg.key), None)
            if f is None or f.value is None:
                raise KeyError(seg.key)
            current = f.value
        else:  # JsonPathIndex
            if not isinstance(current, StdArray):
                raise TypeError('path 段需要 list')
            current = current.elements[seg.index]
    return current
