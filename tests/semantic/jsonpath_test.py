"""semantic/jsonpath.py 统一 JSON path（操作 StdValue）+ python_to_std（dict→AST）测试。

- python_to_std：Python 值 → StdValue 树（!file / !env 外部数据统一入口）
- apply_json_path：StdValue 树投影（key / index / 首段下标 / 缺失报错）
"""

import decimal

import pytest

from infinity_data.parser import JsonPathIndex, JsonPathKey
from infinity_data.semantic.builder.models import (
    StdArray,
    StdLiteral,
    StdObject,
    python_to_std,
)
from infinity_data.semantic.jsonpath import apply_json_path
from infinity_data.tokenizer.models.raw_tokens import SourceRange


def _key(k: str) -> JsonPathKey:
    return JsonPathKey(source=SourceRange.empty(), key=k)


def _idx(i: int) -> JsonPathIndex:
    return JsonPathIndex(source=SourceRange.empty(), index=i)


# ═══════════════════════════════════════════════════════════
# python_to_std（dict → AST）
# ═══════════════════════════════════════════════════════════


def test_python_to_std_scalars() -> None:
    assert python_to_std(1) == StdLiteral(kind='int', value=1)
    assert python_to_std(True) == StdLiteral(kind='bool', value=True)
    assert python_to_std('s') == StdLiteral(kind='str', value='s')
    assert python_to_std(None) == StdLiteral(kind='null', value=None)
    assert python_to_std(1.5) == StdLiteral(kind='float', value=decimal.Decimal('1.5'))


def test_python_to_std_nested() -> None:
    v = python_to_std({'a': 1, 'b': [2, 3], 'c': {'d': 'x'}})
    assert isinstance(v, StdObject)
    assert len(v.fields) == 3
    b = next(f for f in v.fields if f.name == 'b')
    assert isinstance(b.value, StdArray)
    elems = [e for e in b.value.elements if isinstance(e, StdLiteral)]
    assert [e.value for e in elems] == [2, 3]


# ═══════════════════════════════════════════════════════════
# apply_json_path（StdValue 树投影）
# ═══════════════════════════════════════════════════════════


def test_apply_json_path_key_and_index() -> None:
    v = python_to_std({'a': {'b': [10, 20]}})
    assert apply_json_path(v, [_key('a'), _key('b'), _idx(1)]) == StdLiteral(kind='int', value=20)


def test_apply_json_path_first_segment_index() -> None:
    """首段下标：.[N] 直接取根数组元素。"""
    v = python_to_std([10, 20])
    assert apply_json_path(v, [_idx(1)]) == StdLiteral(kind='int', value=20)


def test_apply_json_path_empty_path() -> None:
    """空 path = 整值。"""
    v = python_to_std({'a': 1})
    assert apply_json_path(v, []) == v


def test_apply_json_path_missing_key() -> None:
    v = python_to_std({'a': 1})
    with pytest.raises(KeyError):
        apply_json_path(v, [_key('b')])


def test_apply_json_path_index_out_of_range() -> None:
    v = python_to_std([1])
    with pytest.raises(IndexError):
        apply_json_path(v, [_idx(5)])


def test_apply_json_path_type_mismatch() -> None:
    v = python_to_std({'a': 1})
    with pytest.raises(TypeError):
        apply_json_path(v, [_key('a'), _idx(0)])  # 在标量上取下标
