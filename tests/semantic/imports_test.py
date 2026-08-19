"""semantic/imports.py 单元测试：ImportResolver 命名空间解析。"""

from collections.abc import Mapping
from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import Severity
from infinity_data.infra.file import MemFile
from infinity_data.infra.location import SourceRange
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.imports import ImportResolver, ReportFn


def _report(diags: list[tuple[Severity, str]]) -> ReportFn:
    def _fn(severity: Severity, code: str, params: Mapping[str, object], source: SourceRange | None) -> None:
        diags.append((severity, code))

    return _fn


def test_resolve_env_into_namespace() -> None:
    file = MemFile(name='t.infd', root_path=Path('.'), content='!env import USER\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(env={'USER': 'alice'}), base_dir=Path('.'))
    diags: list[tuple[Severity, str]] = []
    ns = ImportResolver(sandbox=sb).resolve(doc, _report(diags))
    assert ns['USER'] == 'alice'
    assert diags == []


def test_resolve_env_duplicate_binds_first() -> None:
    file = MemFile(name='t.infd', root_path=Path('.'), content='!env import USER\n!env import USER\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(env={'USER': 'alice'}), base_dir=Path('.'))
    diags: list[tuple[Severity, str]] = []
    ns = ImportResolver(sandbox=sb).resolve(doc, _report(diags))
    assert ns['USER'] == 'alice'
    assert any(code == 'namespace.duplicate' for _, code in diags)


def test_resolve_template_path(tmp_path: Path) -> None:
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'x.inft').write_text('~X {\n}\n', encoding='utf-8')
    sb = Sandbox(SandboxConfig(allow_templates=['./templates/*.inft']), base_dir=tmp_path)
    r = ImportResolver(sandbox=sb)
    diags: list[tuple[Severity, str]] = []
    f = r.resolve_template_path('templates/x.inft', base_dir=tmp_path, source=None, report=_report(diags))
    assert f is not None
    assert '~X' in f.read()
