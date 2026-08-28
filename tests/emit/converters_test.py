"""emit 输出转换器测试：to_json / to_yaml / to_toml + EmitConfig（full_float / keep_noexist）。"""

import json
from decimal import Decimal
from pathlib import PurePosixPath

from infinity_data.emit import (
    EmitConfig,
    dump_to_json,
    load_from_json,
    restore_python,
    to_json,
    to_toml,
    to_yaml,
)
from infinity_data.semantic.builder import StdField, StdLiteral, StdObject
from infinity_data.semantic.std import NOEXIST, python_to_std


def _obj(*fields: StdField) -> StdObject:
    return StdObject(fields=list(fields))


# ═══════════════════════════════════════════════════════════
# to_json 默认（有损：path→字符串、noexist 丢弃、Decimal→JSON 数字）
# ═══════════════════════════════════════════════════════════


def test_to_json_default_projection() -> None:
    obj = _obj(
        StdField(name='p', value=StdLiteral(kind='path', value=PurePosixPath('/etc/x'))),
        StdField(name='f', value=StdLiteral(kind='float', value=Decimal('1.5'))),
        StdField(name='i', value=StdLiteral(kind='int', value=2)),
        StdField(name='n', value=StdLiteral(kind='null', value=None)),
        StdField(name='no', value=StdLiteral(kind='noexist', value=None)),  # 默认丢弃
        StdField(name='s', value=StdLiteral(kind='str', value='x')),
    )
    assert json.loads(to_json(obj)) == {'p': '/etc/x', 'f': 1.5, 'i': 2, 'n': None, 's': 'x'}


def test_to_json_integral_decimal_becomes_int() -> None:
    obj = _obj(StdField(name='f', value=StdLiteral(kind='float', value=Decimal('2.0'))))
    assert json.loads(to_json(obj)) == {'f': 2}


def test_to_json_nan_inf_tagged() -> None:
    """NaN / ±Infinity 无法用 JSON 数字表达 → 自描述标记。"""
    obj = _obj(
        StdField(name='nan', value=StdLiteral(kind='float', value=Decimal('NaN'))),
        StdField(name='inf', value=StdLiteral(kind='float', value=Decimal('Infinity'))),
    )
    data = json.loads(to_json(obj))
    assert data == {'nan': {'__type__': 'decimal', 'num': 'NaN'}, 'inf': {'__type__': 'decimal', 'num': 'Infinity'}}


# ═══════════════════════════════════════════════════════════
# full_float / keep_noexist
# ═══════════════════════════════════════════════════════════


def test_to_json_full_float() -> None:
    obj = _obj(StdField(name='f', value=StdLiteral(kind='float', value=Decimal('1.5'))))
    data = json.loads(to_json(obj, config=EmitConfig(full_float=True)))
    assert data == {'f': {'__type__': 'decimal', 'num': '1.5'}}


def test_to_json_full_path() -> None:
    """full_path：路径值以自描述标记编码（默认投影为普通 POSIX 字符串）。"""
    obj = _obj(StdField(name='p', value=StdLiteral(kind='path', value=PurePosixPath('/etc/x'))))
    data = json.loads(to_json(obj, config=EmitConfig(full_path=True)))
    assert data == {'p': {'__type__': 'path', 'path': '/etc/x'}}


def test_to_json_all_full_markers() -> None:
    """full_float + full_path + keep_noexist：全部自描述标记。"""
    obj = _obj(
        StdField(name='p', value=StdLiteral(kind='path', value=PurePosixPath('/etc/x'))),
        StdField(name='f', value=StdLiteral(kind='float', value=Decimal('1.5'))),
        StdField(name='no', value=StdLiteral(kind='noexist', value=None)),
    )
    data = json.loads(to_json(obj, config=EmitConfig(full_float=True, full_path=True, keep_noexist=True)))
    assert data == {
        'p': {'__type__': 'path', 'path': '/etc/x'},
        'f': {'__type__': 'decimal', 'num': '1.5'},
        'no': {'__type__': 'noexist'},
    }


def test_to_json_keep_noexist() -> None:
    obj = _obj(
        StdField(name='a', value=StdLiteral(kind='noexist', value=None)),
        StdField(name='b', value=StdLiteral(kind='int', value=1)),
    )
    data = json.loads(to_json(obj, config=EmitConfig(keep_noexist=True)))
    assert data == {'a': {'__type__': 'noexist'}, 'b': 1}


def test_to_json_from_python_value() -> None:
    """Python 值输入（如 result.value）：PurePosixPath/Decimal/NOEXIST 哨兵均被投影。"""
    value = {'cert': PurePosixPath('/etc/x'), 'f': Decimal('1.5'), 'no': NOEXIST}
    data = json.loads(to_json(value, config=EmitConfig(full_float=True, keep_noexist=True)))
    assert data == {
        'cert': '/etc/x',
        'f': {'__type__': 'decimal', 'num': '1.5'},
        'no': {'__type__': 'noexist'},
    }


def test_to_json_options_indent_and_sort() -> None:
    obj = _obj(
        StdField(name='b', value=StdLiteral(kind='int', value=1)),
        StdField(name='a', value=StdLiteral(kind='int', value=2)),
    )
    text = to_json(obj, config=EmitConfig(indent=None, sort_keys=True))
    assert text == '{"a": 2, "b": 1}'


# ═══════════════════════════════════════════════════════════
# to_yaml / to_toml
# ═══════════════════════════════════════════════════════════


def test_to_yaml() -> None:
    obj = _obj(
        StdField(name='p', value=StdLiteral(kind='path', value=PurePosixPath('/a'))),
        StdField(name='i', value=StdLiteral(kind='int', value=1)),
    )
    text = to_yaml(obj)
    assert 'p: /a' in text
    assert 'i: 1' in text


def test_to_toml() -> None:
    """tool 组保证 tomli-w 已装：to_toml 正常输出。"""
    assert 'a' in to_toml({'a': 1})


# ═══════════════════════════════════════════════════════════
# restore_python：加载的原始 dict → StdPythonValue（标记还原）
# ═══════════════════════════════════════════════════════════


def test_restore_python_markers() -> None:
    raw = {
        'd': {'__type__': 'decimal', 'num': '1.5'},
        'p': {'__type__': 'path', 'path': '/etc/x'},
        'no': {'__type__': 'noexist'},
        'i': 1,
        'b': True,
        's': 'x',
        'n': None,
        'f': 2.5,
    }
    restored = restore_python(raw)
    assert restored == {
        'd': Decimal('1.5'),
        'p': PurePosixPath('/etc/x'),
        'no': NOEXIST,
        'i': 1,
        'b': True,
        's': 'x',
        'n': None,
        'f': Decimal('2.5'),
    }


def test_restore_python_plain_float_to_decimal() -> None:
    """普通 float → Decimal（忠实形式，与 python_to_std 规范一致）。"""
    assert restore_python([1.5, 2, True, 's', None]) == [Decimal('1.5'), 2, True, 's', None]


def test_restore_python_malformed_marker_kept_as_dict() -> None:
    """疑似标记但结构不符 → 按普通 dict 保留（尽力而为）。"""
    assert restore_python({'__type__': 'unknown'}) == {'__type__': 'unknown'}
    assert restore_python({'__type__': 'decimal'}) == {'__type__': 'decimal'}
    assert restore_python({'__type__': 'decimal', 'num': 'abc'}) == {'__type__': 'decimal', 'num': 'abc'}
    assert restore_python({'__type__': 'noexist', 'x': 1}) == {'__type__': 'noexist', 'x': 1}


def test_restore_python_nested() -> None:
    raw = {'a': [{'__type__': 'path', 'path': '/a'}, {'__type__': 'decimal', 'num': 'NaN'}], 'b': {'k': None}}
    restored = restore_python(raw)
    assert isinstance(restored, dict)
    items = restored['a']
    assert isinstance(items, list)
    assert items[0] == PurePosixPath('/a')
    # Decimal NaN 在 IEEE 754 下 != 自身，用 is_nan() 判定
    assert isinstance(items[1], Decimal) and items[1].is_nan()
    assert restored['b'] == {'k': None}


def test_roundtrip_std_through_json_markers() -> None:
    """std → to_json(全标记) → json.loads → restore_python → python_to_std 无损闭环。"""
    obj = StdObject(
        fields=[
            StdField(name='p', value=StdLiteral(kind='path', value=PurePosixPath('/etc/x'))),
            StdField(name='f', value=StdLiteral(kind='float', value=Decimal('1.5'))),
            StdField(name='no', value=StdLiteral(kind='noexist', value=None)),
            StdField(name='i', value=StdLiteral(kind='int', value=1)),
            StdField(name='s', value=StdLiteral(kind='str', value='x')),
        ]
    )
    cfg = EmitConfig(full_float=True, full_path=True, keep_noexist=True)
    raw = json.loads(to_json(obj, config=cfg))
    restored = restore_python(raw)
    assert restored == {
        'p': PurePosixPath('/etc/x'),
        'f': Decimal('1.5'),
        'no': NOEXIST,
        'i': 1,
        's': 'x',
    }
    assert python_to_std(restored) == obj


# ═══════════════════════════════════════════════════════════
# dump_to_json / load_from_json（便捷自由函数，默认保留一切语义）
# ═══════════════════════════════════════════════════════════


def test_dump_to_json_default_preserves_semantics() -> None:
    """dump_to_json 默认开全标记：Decimal / PurePosixPath / noexist 均自描述编码。"""
    value = {'p': PurePosixPath('/etc/x'), 'f': Decimal('1.5'), 'no': NOEXIST, 'i': 1}
    data = json.loads(dump_to_json(value))
    assert data == {
        'p': {'__type__': 'path', 'path': '/etc/x'},
        'f': {'__type__': 'decimal', 'num': '1.5'},
        'no': {'__type__': 'noexist'},
        'i': 1,
    }


def test_dump_to_json_config_override() -> None:
    """传入 config 可覆盖默认：EmitConfig() → 无标记、普通投影。"""
    value = {'p': PurePosixPath('/a'), 'f': Decimal('1.5')}
    assert json.loads(dump_to_json(value, config=EmitConfig())) == {'p': '/a', 'f': 1.5}


def test_load_from_json_restores_semantics() -> None:
    """load_from_json 默认还原：标记 → 专有类型，普通 float → Decimal。"""
    text = json.dumps({'p': {'__type__': 'path', 'path': '/x'}, 'f': 2.5})
    restored = load_from_json(text)
    assert restored == {'p': PurePosixPath('/x'), 'f': Decimal('2.5')}


def test_dump_load_roundtrip_std_is_lossless() -> None:
    """std → dump_to_json → load_from_json → python_to_std 无损闭环（默认即全语义）。"""
    obj = StdObject(
        fields=[
            StdField(name='p', value=StdLiteral(kind='path', value=PurePosixPath('/etc/x'))),
            StdField(name='f', value=StdLiteral(kind='float', value=Decimal('1.5'))),
            StdField(name='no', value=StdLiteral(kind='noexist', value=None)),
            StdField(name='i', value=StdLiteral(kind='int', value=1)),
        ]
    )
    assert python_to_std(load_from_json(dump_to_json(obj))) == obj
