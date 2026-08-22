"""本地注入 !var（§2.10）测试。

- 字面量 / 投影（JSON path）/ 前向引用 / 解包组合 / 模板调用
- 依赖环 → var.cycle；path 取不到 → var.path_failed；别名冲突 → namespace.duplicate
- 不进输出（仅被 $ 引用消费）
"""

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.builder import AstBuilder, StdDocument
from infinity_data.semantic.resolver import ImportResolver, TemplateGraphResolver
from tests.helpers import as_int as _int
from tests.helpers import as_obj as _obj
from tests.helpers import as_str as _str
from tests.helpers import codes as _codes
from tests.helpers import field_of as _field_of
from tests.helpers import root_field as _root_field


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


def test_var_literal_whole() -> None:
    """!var 字面量整值 → $ 引用消费。"""
    std, c = _build('!var { a = 1 } import . as base\nx = $base\n')
    assert not _codes(c)
    assert _int(_field_of(_obj(_root_field(std, 'x')), 'a')) == 1


def test_var_projection() -> None:
    """!var JSON path 投影取子字段。"""
    std, c = _build('!var { a = 1, b = 2 } import . as base\n!var $base import .a as a\ny = $a\n')
    assert not _codes(c)
    assert _int(_root_field(std, 'y')) == 1


def test_var_forward_reference() -> None:
    """前向引用：!var 可引用后面定义的别名（拓扑序求值）。"""
    std, c = _build('!var $later import . as early\n!var { x = 1 } import . as later\ne = $early\n')
    assert not _codes(c)
    assert _int(_field_of(_obj(_root_field(std, 'e')), 'x')) == 1


def test_var_unpack_composition() -> None:
    """!var 值表达式支持解包组合。"""
    std, c = _build('!var { **{ a = 1 }, c = 3 } import . as merged\nm = $merged\n')
    assert not _codes(c)
    obj = _obj(_root_field(std, 'm'))
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(obj, 'c')) == 3


def test_var_template_instance() -> None:
    """!var 值表达式支持模板调用（展开 + 默认值注入）。"""
    std, c = _build('~T {\n    v: int = 5\n}\n!var T() import . as t\ns = $t\n')
    assert not _codes(c)
    assert _int(_field_of(_obj(_root_field(std, 's')), 'v')) == 5


def test_var_array_index_projection() -> None:
    """!var JSON path 数组下标投影（首段为键段，下标在后续段）。"""
    std, c = _build('!var { arr = [10, 20] } import .arr[1] as second\ny = $second\n')
    assert not _codes(c)
    assert _int(_root_field(std, 'y')) == 20


def test_var_first_segment_index() -> None:
    """首段下标：!var [10, 20, 30] import .[2] 直接取根数组元素（§4.4）。"""
    std, c = _build('!var [10, 20, 30] import .[2] as third\ny = $third\n')
    assert not _codes(c)
    assert _int(_root_field(std, 'y')) == 30


def test_var_cycle() -> None:
    """依赖环 → var.cycle。"""
    _, c = _build('!var $a import . as b\n!var $b import . as a\n')
    assert 'var.cycle' in _codes(c)


def test_var_path_failed() -> None:
    """JSON path 取不到 → var.path_failed。"""
    _, c = _build('!var { p = 1 } import .q as x\n')
    assert 'var.path_failed' in _codes(c)


def test_var_namespace_duplicate() -> None:
    """别名重复绑定 → namespace.duplicate（保留先到者）。"""
    std, c = _build('!var { a = 1 } import . as base\n!var { b = 2 } import . as base\nx = $base\n')
    assert 'namespace.duplicate' in _codes(c)
    assert _int(_field_of(_obj(_root_field(std, 'x')), 'a')) == 1  # 先到者


def test_var_not_in_output() -> None:
    """!var 不进输出：仅被 $ 引用消费时才进入产物。"""
    std, c = _build('!var { a = 1 } import . as base\n')
    assert not _codes(c)
    assert std.root.get('base') is None
    assert not list(std.root.fields)


def test_var_string_whole() -> None:
    """!var 字符串整值。"""
    std, c = _build('!var "hello" import . as msg\nm = $msg\n')
    assert not _codes(c)
    assert _str(_root_field(std, 'm')) == 'hello'
