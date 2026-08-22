"""模板可变参数收集（§2.9，模板配置 extra_*_vars）测试。

- 多余位置参数 → 收集到指定字段（list）；未声明命名参数 → 收集到指定字段（dict）
- 约束由收集字段的普通声明承担（零新约束语法）；空收集用字段默认值
- 定义时校验：target 未声明 / 与 positional=false 冲突
- 与 allow_extra 互斥（extra_named_vars 优先收集）
"""

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.builder import AstBuilder, StdDocument
from infinity_data.semantic.resolver import ImportResolver, TemplateGraphResolver
from tests.helpers import (
    arr_values as _arr_values,
)
from tests.helpers import (
    as_int as _int,
)
from tests.helpers import (
    as_obj as _obj,
)
from tests.helpers import (
    as_str as _str,
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


def test_variadic_positional_and_named_collect() -> None:
    """多余位置参数与未声明命名参数分别收集到指定字段。"""
    std, c = _build(
        '~S(extra_positional_vars = rest, extra_named_vars = extra) {\n'
        '    name: str\n'
        '    rest: <list, each(str)> = []\n'
        '    extra: <dict, each(str)> = {}\n'
        '}\n'
        's = S("svc", "a", "b", x = "1", y = "2")\n'
    )
    assert not _codes(c)
    obj = _obj(_root_field(std, 's'))
    assert _str(_field_of(obj, 'name')) == 'svc'
    assert _arr_values(_field_of(obj, 'rest')) == ['a', 'b']
    extra = _obj(_field_of(obj, 'extra'))
    assert _str(_field_of(extra, 'x')) == '1'
    assert _str(_field_of(extra, 'y')) == '2'


def test_variadic_default_when_empty() -> None:
    """无多余参数 → 收集字段用默认值（[] / {}）。"""
    std, c = _build(
        '~S(extra_positional_vars = rest, extra_named_vars = extra) {\n'
        '    rest: <list, each(str)> = []\n'
        '    extra: <dict, each(str)> = {}\n'
        '}\n'
        's = S()\n'
    )
    assert not _codes(c)
    obj = _obj(_root_field(std, 's'))
    assert _arr_values(_field_of(obj, 'rest')) == []
    assert not list(_obj(_field_of(obj, 'extra')).fields)


def test_variadic_collected_constraint() -> None:
    """收集值过字段普通约束（each(str) 收到 int → type_mismatch，executor 执行）。"""
    import tempfile

    from infinity_data import SandboxConfig, load

    d = Path(tempfile.mkdtemp())
    app = d / 't.infd'
    app.write_text('~V(extra_positional_vars = rest) {\n    rest: <list, each(str)> = []\n}\nv = V(1, 2)\n')
    r = load(str(app), sandbox=SandboxConfig.deny_all())
    assert 'constraint.type_mismatch' in [dg.code for dg in r.diagnostics]


def test_variadic_target_missing_definition_time() -> None:
    """extra_*_vars 引用未声明字段 → 定义时（不实例化）即报错。"""
    _, c = _build('~T(extra_named_vars = missing) {\n    a: int = 0\n}\n')
    assert 'template.variadic_target_missing' in _codes(c)


def test_variadic_positional_conflict() -> None:
    """extra_positional_vars 与 positional=false 冲突 → 定义时报错。"""
    _, c = _build('~T(extra_positional_vars = rest, positional = false) {\n    rest: <list> = []\n}\n')
    assert 'template.variadic_positional_conflict' in _codes(c)


def test_variadic_named_overrides_allow_extra() -> None:
    """extra_named_vars 与 allow_extra 并存 → 未声明命名参数一律收集（非平铺）。"""
    std, c = _build(
        '~T(extra_named_vars = extra, allow_extra = true) {\n    extra: <dict, each(int)> = {}\n}\nt = T(foo = 1)\n'
    )
    assert not _codes(c)
    obj = _obj(_root_field(std, 't'))
    # foo 收集进 extra（int 通过 each(int)），而不是平铺为顶层字段
    assert _obj(_field_of(obj, 'extra')).get('foo') is not None
    assert obj.get('foo') is None


def test_variadic_template_as_constraint() -> None:
    """模板即约束：手写 dict 含收集字段时按普通字段校验（零特殊逻辑）。"""
    std, c = _build(
        '~T(extra_named_vars = extra) {\n    a: int = 0\n    extra: <dict, each(int)> = {}\n}\n'
        'x: T = { a = 1, extra = { b = 2 } }\n'
    )
    assert not _codes(c)
    obj = _obj(_root_field(std, 'x'))
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(_obj(_field_of(obj, 'extra')), 'b')) == 2
