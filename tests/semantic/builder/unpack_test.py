"""解包（§2.7）测试：**dict / *list 展开、模板调用解包、类型错误、disjoint merge。"""

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.builder import AstBuilder, StdDocument
from infinity_data.semantic.resolver import ImportResolver, TemplateGraphResolver
from tests.helpers import (
    arr_ints as _arr_ints,
)
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


def test_dict_unpack_literal() -> None:
    std, c = _build('x = { **{ a = 1 }, b = 2 }\n')
    assert not _codes(c)
    obj = _obj(_root_field(std, 'x'))
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(obj, 'b')) == 2


def test_list_unpack_literal() -> None:
    std, c = _build('x = [ *[1, 2], 3 ]\n')
    assert not _codes(c)
    assert _arr_ints(_root_field(std, 'x')) == [1, 2, 3]


def test_dict_unpack_nested() -> None:
    std, c = _build('x = { **{ **{ a = 1 }, b = 2 }, c = 3 }\n')
    assert not _codes(c)
    obj = _obj(_root_field(std, 'x'))
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(obj, 'b')) == 2
    assert _int(_field_of(obj, 'c')) == 3


def test_template_unpack_kwargs() -> None:
    """模板调用 **expr 解包 dict 为命名参数。"""
    std, c = _build('~X {\n    a: int = 0\n    b: int = 0\n}\nx = X(**{ a = 1 })\n')
    assert not _codes(c)
    obj = _obj(_root_field(std, 'x'))
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(obj, 'b')) == 0  # 未提供 → 默认值


def test_template_unpack_args_positional() -> None:
    """模板调用 *expr 解包 list 为位置参数。"""
    std, c = _build('~X {\n    a: int\n    b: int\n}\nx = X(*[1, 2])\n')
    assert not _codes(c)
    obj = _obj(_root_field(std, 'x'))
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(obj, 'b')) == 2


def test_unpack_type_error_dict() -> None:
    _, c = _build('x = { **5 }\n')
    assert 'unpack.type_error' in _codes(c)


def test_unpack_type_error_list() -> None:
    _, c = _build('x = [ *{ a = 1 } ]\n')
    assert 'unpack.type_error' in _codes(c)


def test_unpack_key_conflict() -> None:
    """解包键与字面量键冲突 → dict.duplicate_key，保留先到者（disjoint merge）。"""
    std, c = _build('x = { **{ a = 1 }, a = 2 }\n')
    assert 'dict.duplicate_key' in _codes(c)
    obj = _obj(_root_field(std, 'x'))
    assert _int(_field_of(obj, 'a')) == 1  # 先到者（解包）


def test_template_unpack_kwargs_conflict() -> None:
    """模板调用 ** 解包键与显式参数冲突 → dict.duplicate_key。"""
    _, c = _build('~X {\n    a: int = 0\n}\nx = X(a = 1, **{ a = 2 })\n')
    assert 'dict.duplicate_key' in _codes(c)


def test_unpack_into_array_noexist() -> None:
    """数组解包混入 noexist → value.noexist_in_array（保留位置按 null）。"""
    std, c = _build('x = [ *[1, noexist] ]\n')
    assert 'value.noexist_in_array' in _codes(c)
    assert _arr_values(_root_field(std, 'x')) == [1, None]


def test_unpack_in_template_default() -> None:
    """模板默认值中允许解包（值构造阶段展开）。"""
    std, c = _build('~X {\n    merged: <dict> = { **{ a = 1 }, b = 2 }\n}\nx = X()\n')
    assert not _codes(c)
    merged = _field_of(_obj(_root_field(std, 'x')), 'merged')
    obj = _obj(merged)
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(obj, 'b')) == 2


def test_top_level_unpack_literal() -> None:
    """顶层（隐式 dict）**expr 解包展开为顶层字段。"""
    std, c = _build('**{ a = 1 }\n**{ b = 2 }\n')
    assert not _codes(c)
    assert _int(_root_field(std, 'a')) == 1
    assert _int(_root_field(std, 'b')) == 2


def test_top_level_unpack_conflict() -> None:
    """顶层解包与手写字段冲突 → dict.duplicate_key，保留先到者。"""
    std, c = _build('**{ a = 1 }\na = 2\n')
    assert 'dict.duplicate_key' in _codes(c)
    assert _int(_root_field(std, 'a')) == 1


def test_top_level_unpack_into_template_scope() -> None:
    """顶层解包与模板展开产出的字段合并进同一 root。"""
    std, c = _build('~X {\n    v: int = 1\n}\n**{ a = 1 }\nx = X()\n')
    assert not _codes(c)
    assert _int(_root_field(std, 'a')) == 1
    assert _int(_field_of(_obj(_root_field(std, 'x')), 'v')) == 1


def test_unpack_template_instance_in_dict() -> None:
    """dict 解包模板实例（默认值注入生效）。"""
    std, c = _build('~Inner {\n    a: int = 1\n    b: int = 2\n}\nm = { **Inner(), c = 3 }\n')
    assert not _codes(c)
    obj = _obj(_root_field(std, 'm'))
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(obj, 'b')) == 2
    assert _int(_field_of(obj, 'c')) == 3


def test_unpack_template_instance_in_template_call() -> None:
    """模板调用嵌套：**Inner() 解包为命名参数（字段匹配）。"""
    std, c = _build(
        '~Inner {\n    a: int = 1\n    b: int = 2\n}\n~Outer {\n    a: int = 0\n    b: int = 0\n}\no = Outer(**Inner())\n'
    )
    assert not _codes(c)
    obj = _obj(_root_field(std, 'o'))
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(obj, 'b')) == 2


def test_unpack_template_instance_in_template_default() -> None:
    """模板默认值里解包模板实例（值构造阶段展开）。"""
    std, c = _build('~Inner {\n    a: int = 1\n}\n~X {\n    merged: <dict> = { **Inner(), d = 4 }\n}\nx = X()\n')
    assert not _codes(c)
    merged = _field_of(_obj(_root_field(std, 'x')), 'merged')
    obj = _obj(merged)
    assert _int(_field_of(obj, 'a')) == 1
    assert _int(_field_of(obj, 'd')) == 4


def test_unpack_template_instance_conflict() -> None:
    """模板实例解包键与字面量冲突 → dict.duplicate_key，保留先到者。"""
    std, c = _build('~Inner {\n    a: int = 1\n}\nm = { **Inner(), a = 99 }\n')
    assert 'dict.duplicate_key' in _codes(c)
    assert _int(_field_of(_obj(_root_field(std, 'm')), 'a')) == 1


def test_unpack_template_instance_in_array_error() -> None:
    """数组 * 解包模板实例（dict）→ unpack.type_error（* 需 list）。"""
    _, c = _build('~Inner {\n    a: int = 1\n}\nx = [ *Inner() ]\n')
    assert 'unpack.type_error' in _codes(c)
