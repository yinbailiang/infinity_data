"""重复键规则测试（§1.1 / §2.7）：同一 dict 内同名键一律报错，保留先到者。

- 手写重复键（dict 字面量 / 顶层 root）→ dict.duplicate_key
- 模板调用命名参数重复 → template.dup_argument
- 无重复 → 不误报
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
from tests.helpers import codes as _codes
from tests.helpers import field_of as _field_of
from tests.helpers import root_field as _root_field


def _build(src: str) -> tuple[StdDocument, DiagnosticCollector]:
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    doc, parse_diags = parse_source(file)
    sb = Sandbox(config=SandboxConfig.deny_all(), base_dir=Path('.'))
    resolver = TemplateGraphResolver(import_resolver=ImportResolver(sandbox=sb))
    collector = DiagnosticCollector()
    collector.extend(parse_diags)  # 语法层诊断并入同一收集器（template.dup_argument 属 parser 层）
    context = resolver.resolve(doc, file, collector)
    std = AstBuilder().build(doc, context, collector)
    return std, collector


def test_duplicate_key_dict_literal() -> None:
    """dict 字面量内手写重复键 → ERROR，保留先到者。"""
    std, collector = _build('x = { a = 1, a = 2 }\n')
    assert 'dict.duplicate_key' in _codes(collector)
    assert _int(_field_of(_obj(_root_field(std, 'x')), 'a')) == 1  # 保留先到者


def test_duplicate_key_top_level() -> None:
    """顶层（隐式 dict）重复键 → ERROR，保留先到者。"""
    std, collector = _build('a = 1\na = 2\n')
    assert 'dict.duplicate_key' in _codes(collector)
    assert _int(_root_field(std, 'a')) == 1


def test_duplicate_key_nested() -> None:
    """嵌套 dict 内的重复键独立检测。"""
    std, collector = _build('x = { inner = { b = 1, b = 2 } }\n')
    assert 'dict.duplicate_key' in _codes(collector)
    inner = _field_of(_obj(_root_field(std, 'x')), 'inner')
    assert _int(_field_of(_obj(inner), 'b')) == 1


def test_no_false_positive() -> None:
    """正常 dict / 不同键名 / 嵌套不同层 → 无重复诊断。"""
    _, collector = _build('x = { a = 1, b = 2 }\ny = { a = 1 }\n')
    assert 'dict.duplicate_key' not in _codes(collector)


def test_template_expansion_no_false_positive() -> None:
    """模板展开（字段 + 默认值 + 命名参数覆盖默认值）不触发重复键。"""
    _, collector = _build('~X {\n    v: int = 1\n    w: int = 2\n}\nx = X(v = 3)\n')
    assert 'dict.duplicate_key' not in _codes(collector)
    assert 'template.dup_argument' not in _codes(collector)


def test_dup_argument_template_call() -> None:
    """模板调用命名参数重复 → template.dup_argument。"""
    _, collector = _build('~X {\n    v: int = 1\n}\nx = X(v = 1, v = 2)\n')
    assert 'template.dup_argument' in _codes(collector)


def test_dup_argument_across_positional_and_named() -> None:
    """位置 + 命名给同一字段 → 既有 template.arg_conflict（不新增 dup_argument）。"""
    _, collector = _build('~X {\n    v: int\n}\nx = X(1, v = 2)\n')
    assert 'template.arg_conflict' in _codes(collector)
