"""semantic/builder/builder.py 单元测试：AstBuilder（Phase 2a 纯构建）。

与 Phase 1 / Phase 2b 零耦合：测试手工组装「Phase 1 求解 → Phase 2a 构建」，
诊断经共享 DiagnosticCollector 收集（构建产物 StdDocument 不含诊断）。
"""

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector, Severity
from infinity_data.infra.file import MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.builder import AstBuilder, StdDocument, StdObject
from infinity_data.semantic.resolver import ImportResolver, TemplateGraphResolver


def _build(src: str) -> tuple[StdDocument, DiagnosticCollector]:
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    doc, _ = parse_source(file)
    sb = Sandbox(config=SandboxConfig.deny_all(), base_dir=Path('.'))
    resolver = TemplateGraphResolver(import_resolver=ImportResolver(sandbox=sb))
    collector = DiagnosticCollector()
    context = resolver.resolve(doc, file, collector)
    std = AstBuilder().build(doc, context, collector)
    return std, collector


def _has_errors(collector: DiagnosticCollector) -> bool:
    return any(d.severity is Severity.ERROR for d in collector)


def _codes(collector: DiagnosticCollector) -> list[str]:
    return [d.code for d in collector]


def test_build_builds_root() -> None:
    std, collector = _build('a = 1\nb = "x"\n')
    assert not _has_errors(collector)
    assert std.root.get('a') is not None
    assert std.root.get('b') is not None


def test_build_template_expansion() -> None:
    std, collector = _build('~X {\n    v: int = 1\n}\nx = X()\n')
    assert not _has_errors(collector)
    field = std.root.get('x')
    assert field is not None
    assert isinstance(field.value, StdObject)
    assert field.value.get('v') is not None


def test_build_value_less_field_reported() -> None:
    _, collector = _build('x\n')
    assert _has_errors(collector)
    assert 'field.missing_value' in _codes(collector)


def test_build_empty_source() -> None:
    _, collector = _build('')
    assert not _has_errors(collector)
