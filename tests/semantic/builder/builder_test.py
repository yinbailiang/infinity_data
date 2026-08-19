"""semantic/builder.py 单元测试：AstBuilder（Phase 2a 构建 + 编排）。"""

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.file import MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.builder import AstBuilder
from infinity_data.semantic.imports import ImportResolver
from infinity_data.semantic.models import StdObject
from infinity_data.semantic.registry import ConstraintRegistry
from infinity_data.semantic.resolver import TemplateGraphResolver


def _build(src: str):
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    doc, _ = parse_source(file)
    sb = Sandbox(config=SandboxConfig.deny_all(), base_dir=Path('.'))
    resolver = TemplateGraphResolver(
        registry=ConstraintRegistry(),
        import_resolver=ImportResolver(sandbox=sb),
        schema=None,
    )
    return AstBuilder(resolver=resolver).analyze(doc, file)


def test_analyze_builds_root() -> None:
    std = _build('a = 1\nb = "x"\n')
    assert not std.has_errors
    assert std.root.get('a') is not None
    assert std.root.get('b') is not None


def test_analyze_template_expansion() -> None:
    std = _build('~X {\n    v: int = 1\n}\nx = X()\n')
    assert not std.has_errors
    field = std.root.get('x')
    assert field is not None
    assert isinstance(field.value, StdObject)
    assert field.value.get('v') is not None


def test_analyze_value_less_field_reported() -> None:
    std = _build('x\n')
    assert std.has_errors
    assert any(d.code == 'field.missing_value' for d in std.diagnostics)


def test_analyze_empty_source() -> None:
    std = _build('')
    assert not std.has_errors
