"""emit 零依赖 YAML emitter 测试：block 风格、标量引用、多行字符串。"""

from __future__ import annotations

from decimal import Decimal
from pathlib import PurePosixPath

from infinity_data.emit.plain_yaml import yaml_dump


def test_simple_mapping() -> None:
    assert yaml_dump({'a': 1, 'b': 'x', 'c': True}) == 'a: 1\nb: x\nc: true'


def test_empty_containers() -> None:
    assert yaml_dump({}) == '{}'
    assert yaml_dump([]) == '[]'
    assert yaml_dump({'a': {}}) == 'a: {}'
    assert yaml_dump({'a': []}) == 'a: []'


def test_nested_mapping_and_list() -> None:
    text = yaml_dump({'a': {'b': [1, 2], 'c': {'d': 'x'}}})
    assert text == 'a:\n  b:\n    - 1\n    - 2\n  c:\n    d: x'


def test_list_of_mappings() -> None:
    text = yaml_dump({'items': [{'n': 1, 's': 'a'}, {'n': 2}]})
    assert text == 'items:\n  - n: 1\n    s: a\n  - n: 2'


def test_null_and_decimal() -> None:
    text = yaml_dump({'n': None, 'f': Decimal('1.5'), 'i': Decimal('2')})
    assert text == 'n: null\nf: 1.5\ni: 2'


def test_string_quoting_ambiguous_literals() -> None:
    """YAML 1.1 歧义字面量（null/true/yes/no 等字符串值）必须加引号。"""
    text = yaml_dump({'k': 'true', 'v': 'no', 'e': '', 'y': 'null'})
    assert text == "k: 'true'\nv: 'no'\ne: ''\ny: 'null'"


def test_string_quoting_special_chars() -> None:
    """首字符歧义 / 含冒号空格 / 内嵌注释符 → 加单引号；合法普通标量不加。"""
    text = yaml_dump(
        {
            'a': '- dash',  # 首字符 '-'
            'b': 'has: colon',  # 含 ': '
            'c': "it's",  # 合法普通标量（引号在词中）
            'd': '12:30',  # 冒号后无空格 → 合法普通标量
            'e': 'x #comment',  # 内嵌 ' #' → 需引号
            'f': 'trail ',  # 尾部空格 → 需引号
        }
    )
    assert text == ("a: '- dash'\nb: 'has: colon'\nc: it's\nd: 12:30\ne: 'x #comment'\nf: 'trail '")


def test_multiline_string_block() -> None:
    text = yaml_dump({'note': 'line1\nline2\n'})
    assert text == 'note: |-\n  line1\n  line2'


def test_multiline_string_in_list() -> None:
    text = yaml_dump(['a\nb', 'c'])
    assert text == '- |-\n  a\n  b\n- c'


def test_path_value_projected_to_string() -> None:
    """PurePosixPath（忠实转换产物）→ 普通字符串输出。"""
    text = yaml_dump({'p': PurePosixPath('/etc/x')})
    assert text == 'p: /etc/x'
