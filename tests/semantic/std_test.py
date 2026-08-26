"""semantic/std.py：python_to_std ↔ std_to_python 忠实互转（语义最小丢失）。

与 emit 的有损投影（path → 字符串）区分：本层是**忠实双向**——
path 保持 :class:`PosixPath`、float 保持 :class:`decimal.Decimal`，可 round-trip。
"""

from decimal import Decimal
from pathlib import PosixPath, PurePosixPath, PureWindowsPath
from typing import Any, TypeAliasType, cast

from infinity_data.emit import restore_python
from infinity_data.semantic.builder import StdArray, StdField, StdLiteral, StdObject
from infinity_data.semantic.std import NOEXIST, StdPythonValue, python_to_std, std_to_python


def test_roundtrip_scalars() -> None:
    assert std_to_python(python_to_std(1)) == 1
    assert std_to_python(python_to_std(True)) is True
    assert std_to_python(python_to_std('x')) == 'x'
    assert std_to_python(python_to_std(None)) is None
    assert std_to_python(python_to_std(Decimal('1.5'))) == Decimal('1.5')
    # float 经 restore_python 归一到 Decimal（忠实形式）：round-trip 后仍是 Decimal，不是 float
    assert std_to_python(python_to_std(restore_python(1.5))) == Decimal('1.5')


def test_std_python_value_is_recursive_type_alias() -> None:
    """StdPythonValue 是 PEP 695 递归类型别名（可作为标注使用）。"""
    assert isinstance(StdPythonValue, TypeAliasType)
    # 类型层 smoke：忠实 round-trip 的结果符合规范形式
    v: StdPythonValue = std_to_python(python_to_std(restore_python({'a': 1, 'b': [True, 'x']})))
    assert v == {'a': 1, 'b': [True, 'x']}
    p: StdPythonValue = std_to_python(python_to_std(PosixPath('/etc/x')))
    assert p == PosixPath('/etc/x')


def test_roundtrip_path_keeps_posix_path() -> None:
    """path 双向忠实：python_to_std(PosixPath) → path → 逆回 PosixPath（非字符串）。"""
    v = python_to_std(PosixPath('/etc/x'))
    assert isinstance(v, StdLiteral) and v.kind == 'path'
    assert std_to_python(v) == PosixPath('/etc/x')


def test_python_to_std_accepts_any_pure_path() -> None:
    """任意 pathlib 路径 → path 值（运行时便利：签名契约之外仍容忍，§1.5）。"""
    a = python_to_std(cast(Any, PurePosixPath('/a/b')))
    assert isinstance(a, StdLiteral) and a.kind == 'path'
    b = python_to_std(cast(Any, PureWindowsPath('C:/x')))
    assert isinstance(b, StdLiteral) and b.value == PosixPath('C:/x')


def test_three_state_roundtrip() -> None:
    """转换层默认无损：noexist 保留为 NOEXIST；keep_null=False 丢弃 null。"""
    obj = StdObject(
        fields=[
            StdField(name='a', value=StdLiteral(kind='noexist', value=None)),
            StdField(name='b', value=StdLiteral(kind='null', value=None)),
            StdField(name='c', value=StdLiteral(kind='int', value=1)),
        ]
    )
    assert std_to_python(obj) == {'a': NOEXIST, 'b': None, 'c': 1}
    assert std_to_python(obj, keep_null=False) == {'a': NOEXIST, 'c': 1}
    # 输出投影语义：显式丢弃 noexist（§1.6 键不出现）
    assert std_to_python(obj, keep_noexist=False) == {'b': None, 'c': 1}
    assert std_to_python(obj, keep_null=False, keep_noexist=False) == {'c': 1}


def test_nested_roundtrip() -> None:
    obj = StdObject(
        fields=[
            StdField(
                name='s',
                value=StdObject(fields=[StdField(name='p', value=StdLiteral(kind='path', value=PosixPath('/x')))]),
            ),
            StdField(
                name='l',
                value=StdArray(elements=[StdLiteral(kind='int', value=1), StdLiteral(kind='str', value='a')]),
            ),
        ]
    )
    assert std_to_python(obj) == {'s': {'p': PosixPath('/x')}, 'l': [1, 'a']}


# ═══════════════════════════════════════════════════════════
# noexist 三态：NOEXIST 哨兵（Python 域的三态表示）
# ═══════════════════════════════════════════════════════════


def test_noexist_sentinel_distinct_from_none() -> None:
    assert NOEXIST is not None
    assert NOEXIST == NOEXIST
    assert (NOEXIST == None) is False  # noqa: E711


def test_python_to_std_accepts_noexist_sentinel() -> None:
    """Python 侧可用 NOEXIST 表达三态：{a: NOEXIST} → a=noexist；{a: None} → a=null。"""
    v = python_to_std(restore_python({'a': NOEXIST, 'b': None, 'c': 1}))
    assert isinstance(v, StdObject)
    fields = {f.name: f.value for f in v.fields}
    assert isinstance(fields['a'], StdLiteral) and fields['a'].kind == 'noexist'
    assert isinstance(fields['b'], StdLiteral) and fields['b'].kind == 'null'
    assert isinstance(fields['c'], StdLiteral) and fields['c'].kind == 'int'
    n = python_to_std(NOEXIST)
    assert isinstance(n, StdLiteral) and n.kind == 'noexist'


def test_std_to_python_keep_noexist_preserves_sentinel() -> None:
    """noexist **默认**保留为 NOEXIST（转换层无损）；keep_noexist=False 丢弃（输出投影）。"""
    obj = StdObject(
        fields=[
            StdField(name='a', value=StdLiteral(kind='noexist', value=None)),
            StdField(name='b', value=StdLiteral(kind='null', value=None)),
        ]
    )
    assert std_to_python(obj) == {'a': NOEXIST, 'b': None}
    assert std_to_python(obj, keep_noexist=True) == {'a': NOEXIST, 'b': None}
    assert std_to_python(obj, keep_noexist=False) == {'b': None}


def test_noexist_roundtrip_is_lossless_by_default() -> None:
    """python_to_std ↔ std_to_python 三态**默认**无损 round-trip（无需显式参数）。"""
    src = {'a': NOEXIST, 'b': None, 'c': 1}
    back = std_to_python(python_to_std(restore_python(src)))
    assert isinstance(back, dict)
    assert back == src
    assert back['a'] is NOEXIST
