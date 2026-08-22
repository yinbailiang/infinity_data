"""测试共享 helper：StdAst 断言工具（消除多文件重复的 _codes/_int/_obj 等）。"""

from __future__ import annotations

from typing import cast

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.semantic.builder import StdArray, StdDocument, StdField, StdLiteral, StdObject


def codes(c: DiagnosticCollector) -> list[str]:
    """诊断码列表。"""
    return [d.code for d in c]


def field_of(obj: StdObject, name: str) -> StdField:
    """取对象字段（断言存在）。"""
    f = obj.get(name)
    assert f is not None
    return f


def root_field(std: StdDocument, name: str) -> StdField:
    """取 root 字段（断言存在）。"""
    return field_of(std.root, name)


def as_int(field: StdField) -> int:
    """断言字段值为 int 字面量并返回其值。"""
    assert isinstance(field.value, StdLiteral)
    assert field.value.kind == 'int'
    return cast(int, field.value.value)


def as_str(field: StdField) -> str:
    """断言字段值为 str 字面量并返回其值。"""
    assert isinstance(field.value, StdLiteral)
    assert field.value.kind == 'str'
    return cast(str, field.value.value)


def as_obj(field: StdField) -> StdObject:
    """断言字段值为 dict 并返回。"""
    assert isinstance(field.value, StdObject)
    return field.value


def as_arr(field: StdField) -> StdArray:
    """断言字段值为 list 并返回。"""
    assert isinstance(field.value, StdArray)
    return field.value


def arr_ints(field: StdField) -> list[int]:
    """断言字段值为 int 列表并返回其值。"""
    out: list[int] = []
    for e in as_arr(field).elements:
        assert isinstance(e, StdLiteral)
        assert e.kind == 'int'
        out.append(cast(int, e.value))
    return out


def arr_values(field: StdField) -> list[object]:
    """断言字段值为 list，返回元素 Python 值（null → None）。"""
    out: list[object] = []
    for e in as_arr(field).elements:
        assert isinstance(e, StdLiteral)
        out.append(None if e.kind == 'null' else e.value)
    return out
