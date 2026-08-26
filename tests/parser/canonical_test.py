"""AST canonical（标准 infd 源码，round-trip）测试。

- ``canonical()`` 输出**标准 infd 源码**，可被 :func:`parse_source` 解析回等价 AST
- 不动点：``parse(canonical(x)).canonical() == canonical(x)``（规范化稳定）
- 注释 / 空白 / 尾逗号 / 单约束省略尖括号 → 相同 canonical
- 位置 / 命名参数保持源码顺序（含 ``*`` / ``**`` 解包项，round-trip 语义等价）
"""

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.file import MemFile
from infinity_data.parser import Document, Field, TemplateDef


def _parse(src: str) -> Document:
    doc, _ = parse_source(MemFile(name='t.infd', root_path=Path('.'), content=src))
    return doc


def _tpl(doc: Document, name: str) -> TemplateDef:
    for s in doc.statements:
        if isinstance(s, TemplateDef) and s.name == name:
            return s
    raise AssertionError(f'template {name!r} not found')


def _field(doc: Document) -> Field:
    for s in doc.statements:
        if isinstance(s, Field):
            return s
    raise AssertionError('no field found')


# ═══════════════════════════════════════════════════════════
# round-trip 不动点
# ═══════════════════════════════════════════════════════════


def test_canonical_template_fixed_point() -> None:
    src = '~Server {\n    host: str = "0.0.0.0"\n    port: <int, range(1, 65535)> = 80\n    tls: bool = false\n}\n'
    tpl = _tpl(_parse(src), 'Server')
    c = tpl.canonical()
    # canonical 输出是合法 infd，可再解析
    assert _tpl(_parse(c), 'Server').canonical() == c  # 不动点


def test_canonical_complex_fixed_point() -> None:
    """嵌套 / 结构级约束 / 模板调用 / 解包 / 可空自引用 round-trip。"""
    src = (
        '~Node {\n'
        '    name: str\n'
        '    child: <Node?> = null\n'
        '    : <when(field(port, eq(443)), field(tls, eq(true)))>\n'
        '}\n'
        'n = Node(name = "x", child = Node())\n'
    )
    tpl = _tpl(_parse(src), 'Node')
    c = tpl.canonical()
    assert _tpl(_parse(c), 'Node').canonical() == c


def test_canonical_field_fixed_point() -> None:
    """值级（dict 字面量 + 解包 + 数组解包）round-trip。"""
    src = 'x = { a = 1, b = [1, 2, *[3]], c = { **{ d = "s" } } }\n'
    f = _field(_parse(src))
    c = f.canonical()
    assert _field(_parse(c)).canonical() == c


def test_canonical_template_call_fixed_point() -> None:
    """模板调用（位置 + 命名 + 解包）round-trip。"""
    src = 'x = T(1, "a", b = 2, **{ c = 3 }, *[4])\n'
    f = _field(_parse(src))
    c = f.canonical()
    assert _field(_parse(c)).canonical() == c


def test_canonical_template_call_unpack_order_fixed_point() -> None:
    """*expr 解包与显式位置参数交错：canonical 保持源码顺序（语义等价 round-trip）。"""
    src = 'x = T(*[1, 2, 3], 4, 5, *[6], 7)\n'
    f = _field(_parse(src))
    c = f.canonical()
    assert '*[ 1, 2, 3 ], 4, 5, *[ 6 ], 7' in c  # 解包项不挪位
    assert _field(_parse(c)).canonical() == c  # 不动点


def test_canonical_template_call_named_unpack_order_fixed_point() -> None:
    """** 解包项与显式命名参数交错：canonical 保持源码顺序（round-trip 语义等价）。"""
    src = 'x = T(b = 2, **{ a = 1 }, c = 3)\n'
    f = _field(_parse(src))
    c = f.canonical()
    assert 'b = 2, **{ a = 1 }, c = 3' in c  # ** 解包项不挪位
    assert _field(_parse(c)).canonical() == c  # 不动点


def test_canonical_string_escaping_round_trip() -> None:
    """含转义/中文/特殊字符的字符串 round-trip。"""
    src = 'x = { msg = "a\\"b\\n中文\\t\\u00e9", path = "C:\\\\x" }\n'
    f = _field(_parse(src))
    c = f.canonical()
    assert _field(_parse(c)).canonical() == c


def test_canonical_float_forms_round_trip() -> None:
    """浮点（含 nan / ±inf）round-trip。"""
    src = 'x = { a = 1.5e3, b = nan, c = +inf, d = -inf }\n'
    f = _field(_parse(src))
    c = f.canonical()
    assert _field(_parse(c)).canonical() == c


# ═══════════════════════════════════════════════════════════
# 规范化（等价源码 → 相同 canonical）
# ═══════════════════════════════════════════════════════════


def test_canonical_ignores_comments_and_whitespace() -> None:
    a = _tpl(_parse('~X {\n    a: int = 1\n}\n'), 'X').canonical()
    b = _tpl(_parse('~X {\n    # 注释行\n    a: int = 1,   # 尾注\n}\n'), 'X').canonical()
    assert a == b


def test_canonical_single_constraint_brackets_equivalence() -> None:
    """单约束省略尖括号与显式 <...> 等价。"""
    a = _tpl(_parse('~X {\n    a: int = 1\n}\n'), 'X').canonical()
    b = _tpl(_parse('~X {\n    a: <int> = 1\n}\n'), 'X').canonical()
    assert a == b


def test_canonical_preserves_arg_order() -> None:
    """位置/命名参数（含 ** 解包项）保持源码顺序（确定性，round-trip 语义等价）。"""
    c = _field(_parse('x = T(b = 2, a = 1, **{ c = 3 }, d = 4)\n')).canonical()
    assert c == 'x = T(b = 2, a = 1, **{ c = 3 }, d = 4)'


def test_canonical_top_level_unpack_fixed_point() -> None:
    """顶层 ** 解包语句 round-trip 不动点。"""
    doc = _parse('**{ a = 1 }\n**{ b = 2 }\n')
    c = doc.canonical()
    assert _parse(c).canonical() == c
