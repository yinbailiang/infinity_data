"""模板在 list 上展开（§2.8）测试。

- 参数级 ``...`` = 展开轴（zip 默认）；调用级 ``...`` = 展开传播（内层展开结果作外层轴）
- 调用级 ``^`` = 笛卡尔积（多轴全组合，首轴最慢变化；与传播可叠加 ``^...``）
- ``**`` 解包轴（list[dict] 逐元素解包）；结果恒为 list
- 错误：轴非 list / zip 长度不等 / 调用级 ``^``/``...`` 无展开源 / 后缀反序 / ``...`` 普通值位置
"""

import tempfile
from pathlib import Path

from infinity_data import SandboxConfig, load
from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.sandbox import Sandbox
from infinity_data.semantic.builder import AstBuilder, StdDocument, StdField, StdObject
from infinity_data.semantic.resolver import ImportResolver, TemplateGraphResolver
from tests.helpers import (
    as_arr as _as_arr,
)
from tests.helpers import (
    as_int as _as_int,
)
from tests.helpers import (
    as_str as _as_str,
)
from tests.helpers import (
    codes as _codes,
)
from tests.helpers import (
    field_of as _field_of,
)
from tests.helpers import (
    root_field as _root_field,
)


def _build(src: str) -> tuple[StdDocument, DiagnosticCollector]:
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    doc, parse_diags = parse_source(file)
    sb = Sandbox(config=SandboxConfig.deny_all(), base_dir=Path('.'))
    resolver = TemplateGraphResolver(import_resolver=ImportResolver(sandbox=sb))
    collector = DiagnosticCollector()
    collector.extend(parse_diags)
    context = resolver.resolve(doc, file, collector)
    std = AstBuilder().build(doc, context, collector)
    return std, collector


def _arr_objs(field: StdField) -> list[StdObject]:
    arr = _as_arr(field)
    objs: list[StdObject] = []
    for e in arr.elements:
        assert isinstance(e, StdObject)
        objs.append(e)
    return objs


def test_expand_single_axis_zip() -> None:
    """单轴 zip：每个元素一个实例（默认值注入）。"""
    std, c = _build(
        '~Node {\n    host: str = "?"\n    port: <int, range(1, 65535)> = 80\n}\nx = Node(host = ["a", "b"]...)\n'
    )
    assert not _codes(c)
    arr = _as_arr(_root_field(std, 'x'))
    assert len(arr.elements) == 2
    objs = [e for e in arr.elements if isinstance(e, StdObject)]
    assert _as_str(_field_of(objs[0], 'host')) == 'a'
    assert _as_str(_field_of(objs[1], 'host')) == 'b'
    assert _as_int(_field_of(objs[0], 'port')) == 80  # 默认值


def test_expand_multi_axis_zip() -> None:
    """多轴 zip：等长配对。"""
    std, c = _build(
        '~Node {\n    host: str\n    port: <int, range(1, 65535)> = 80\n}\n'
        'x = Node(host = ["a", "b"]..., port = [8080, 9090]...)\n'
    )
    assert not _codes(c)
    objs = _arr_objs(_root_field(std, 'x'))
    assert _as_str(_field_of(objs[0], 'host')) == 'a'
    assert _as_int(_field_of(objs[0], 'port')) == 8080
    assert _as_str(_field_of(objs[1], 'host')) == 'b'
    assert _as_int(_field_of(objs[1], 'port')) == 9090


def test_expand_propagate() -> None:
    """调用级 ... = 展开传播：内层展开结果作为外层调用轴，整个模式逐元素重复。"""
    std, c = _build('~A { v: int }\n~B { a: A }\n!var [1, 2, 3] import . as xs\nx = B(a = A(v = $xs...)...)\n')
    assert not _codes(c)
    objs = _arr_objs(_root_field(std, 'x'))
    assert len(objs) == 3
    for i, o in enumerate(objs):
        a = _field_of(o, 'a')
        assert isinstance(a.value, StdObject)
        assert _as_int(_field_of(a.value, 'v')) == i + 1


def test_expand_propagate_chain() -> None:
    """链式传播：每层显式 ... ，整体模式逐元素重复（C(B(A(·)))）。"""
    std, c = _build(
        '~A { v: int }\n~B { a: A }\n~C { b: B }\n!var [1, 2] import . as xs\nx = C(b = B(a = A(v = $xs...)...)...)\n'
    )
    assert not _codes(c)
    objs = _arr_objs(_root_field(std, 'x'))
    assert len(objs) == 2
    for i, o in enumerate(objs):
        b = _field_of(o, 'b')
        assert isinstance(b.value, StdObject)
        a = _field_of(b.value, 'a')
        assert isinstance(a.value, StdObject)
        assert _as_int(_field_of(a.value, 'v')) == i + 1


def test_expand_propagate_top_noop() -> None:
    """顶层字段尾部 ...：无包围模板调用 → no-op（结果仍为本调用展开 list）。"""
    std, c = _build('~A { v: int = 0 }\nx = A(v = [1, 2]...)...\n')
    assert not _codes(c)
    objs = _arr_objs(_root_field(std, 'x'))
    assert len(objs) == 2
    assert _as_int(_field_of(objs[0], 'v')) == 1
    assert _as_int(_field_of(objs[1], 'v')) == 2


def test_expand_propagate_named_no_source() -> None:
    """内层调用无展开源 + 调用级 ... → 恰好一次 template.expand_no_source（不重复报错）。"""
    std, c = _build('~A { v: int = 0 }\n~B { a: A }\nx = B(a = A(v = 5)...)\n')
    codes = _codes(c)
    assert codes.count('template.expand_no_source') == 1
    # 内层无源时报错并退回单实例（x 仍在产物中，为一个 B 实例）
    x = _root_field(std, 'x')
    assert isinstance(x.value, StdObject)
    a = _field_of(x.value, 'a')
    assert isinstance(a.value, StdObject)
    assert _as_int(_field_of(a.value, 'v')) == 5


def test_expand_unpack_axis() -> None:
    """** 解包轴：list[dict] 逐元素解包为命名参数（§2.8 关键组合）。"""
    std, c = _build(
        '~Service {\n    name: str\n    port: int = 80\n}\n'
        '!var [{ name = "x", port = 1 }, { name = "y", port = 2 }] import . as svcs\n'
        's = Service(**$svcs...)\n'
    )
    assert not _codes(c)
    objs = _arr_objs(_root_field(std, 's'))
    assert len(objs) == 2
    assert _as_str(_field_of(objs[0], 'name')) == 'x'
    assert _as_int(_field_of(objs[0], 'port')) == 1
    assert _as_str(_field_of(objs[1], 'name')) == 'y'


def test_expand_splice_into_array() -> None:
    """展开结果 splice 进数组（与 * 解包组合）。"""
    std, c = _build('~N { a: int = 0 }\nx = [*N(a = [1, 2]...)..., 99]\n')
    assert not _codes(c)
    arr = _as_arr(_root_field(std, 'x'))
    vals: list[object] = []
    for e in arr.elements:
        if isinstance(e, StdObject):
            vals.append(_as_int(_field_of(e, 'a')))
        else:
            from infinity_data.semantic.builder import StdLiteral

            assert isinstance(e, StdLiteral)
            vals.append(e.value)
    assert vals == [1, 2, 99]


def test_expand_not_list() -> None:
    """轴非 list → template.expand_not_list。"""
    _, c = _build('!var "hi" import . as s\n~T { a: str = "" }\nx = T(a = $s...)\n')
    assert 'template.expand_not_list' in _codes(c)


def test_expand_length_mismatch() -> None:
    """zip 多轴长度不等 → template.expand_length_mismatch。"""
    _, c = _build('~T { a: int = 0, b: int = 0 }\nx = T(a = [1]..., b = [1, 2]...)\n')
    assert 'template.expand_length_mismatch' in _codes(c)


def test_expand_no_source() -> None:
    """调用级 ... 但零轴（无展开源）→ template.expand_no_source。"""
    _, c = _build('~T { a: int = 0 }\nx = T()...\n')
    assert 'template.expand_no_source' in _codes(c)


def test_expand_cartesian() -> None:
    """调用级 ^ = 笛卡尔积：多轴全组合，首轴最慢变化（可审计、可预测）。"""
    std, c = _build(
        '~Node {\n    host: str\n    port: <int, range(1, 65535)> = 80\n}\n'
        'x = Node(host = ["a", "b"]..., port = [443, 8443]...)^\n'
    )
    assert not _codes(c)
    objs = _arr_objs(_root_field(std, 'x'))
    assert len(objs) == 4
    # 首轴（host）最慢变化：a×{443,8443}, b×{443,8443}
    pairs = [(_as_str(_field_of(o, 'host')), _as_int(_field_of(o, 'port'))) for o in objs]
    assert pairs == [('a', 443), ('a', 8443), ('b', 443), ('b', 8443)]


def test_expand_cartesian_single_axis_noop() -> None:
    """单轴 + 调用级 ^ → 合法 no-op（1 个轴无 zip/积之分）。"""
    std, c = _build('~T { a: int = 0 }\nx = T(a = [1, 2]...)^\n')
    assert not _codes(c)
    objs = _arr_objs(_root_field(std, 'x'))
    assert len(objs) == 2
    assert _as_int(_field_of(objs[0], 'a')) == 1
    assert _as_int(_field_of(objs[1], 'a')) == 2


def test_expand_cartesian_propagate() -> None:
    """积 + 传播（^...）：A 积展开结果作为包围调用 B 的轴。"""
    std, c = _build(
        '~A { h: str, p: int }\n'
        '~B { a: A }\n'
        '!var ["a", "b"] import . as hs\n'
        '!var [80, 443] import . as ps\n'
        'x = B(a = A(h = $hs..., p = $ps...)^...)\n'
    )
    assert not _codes(c)
    objs = _arr_objs(_root_field(std, 'x'))
    assert len(objs) == 4  # 2×2 积展开后逐元素构造 B
    pairs: list[tuple[str, int]] = []
    for o in objs:
        a = _field_of(o, 'a')
        assert isinstance(a.value, StdObject)
        pairs.append((_as_str(_field_of(a.value, 'h')), _as_int(_field_of(a.value, 'p'))))
    assert pairs == [('a', 80), ('a', 443), ('b', 80), ('b', 443)]


def test_expand_cartesian_no_source() -> None:
    """零轴 + 调用级 ^ → template.expand_no_source。"""
    _, c = _build('~T { a: int = 0 }\nx = T()^\n')
    assert 'template.expand_no_source' in _codes(c)


def test_expand_suffix_order() -> None:
    """后缀反序 ...^ → parse.expand_suffix_order（^ 必须先于 ...）。"""
    _, c = _build('~T { a: int = 0 }\nx = T(a = [1]...)...^\n')
    assert 'parse.expand_suffix_order' in _codes(c)


def test_expand_outside_call() -> None:
    """... 在普通值位置 → parse.expand_outside_call。"""
    _, c = _build('!var 1 import . as n\nx = [$n...]\n')
    assert 'parse.expand_outside_call' in _codes(c)


def test_expand_with_constraints() -> None:
    """展开实例的约束照常执行（每个实例完整校验）。"""
    d = Path(tempfile.mkdtemp())
    app = d / 't.infd'
    app.write_text('~Node {\n    port: <int, range(1, 65535)> = 80\n}\nx = Node(port = [80, 99999]...)\n')
    r = load(str(app), sandbox=SandboxConfig.deny_all())
    assert 'constraint.range_above' in [dg.code for dg in r.diagnostics]
