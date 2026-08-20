"""semantic/resolver/imports.py 单元测试：ImportResolver 命名空间解析。"""

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.resolver import ImportResolver


def _codes(collector: DiagnosticCollector) -> list[str]:
    return [d.code for d in collector]


def test_resolve_env_into_namespace() -> None:
    file = MemFile(name='t.infd', root_path=Path('.'), content='!env import USER\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(env={'USER': 'alice'}), base_dir=Path('.'))
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert ns['USER'] == 'alice'
    assert not list(collector)


def test_resolve_env_duplicate_binds_first() -> None:
    file = MemFile(name='t.infd', root_path=Path('.'), content='!env import USER\n!env import USER\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(env={'USER': 'alice'}), base_dir=Path('.'))
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert ns['USER'] == 'alice'
    assert 'namespace.duplicate' in _codes(collector)


def test_resolve_template_path(tmp_path: Path) -> None:
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'x.inft').write_text('~X {\n}\n', encoding='utf-8')
    sb = Sandbox(SandboxConfig(allow_templates=['./templates/*.inft']), base_dir=tmp_path)
    r = ImportResolver(sandbox=sb)
    collector = DiagnosticCollector()
    f = r.resolve_template_path('templates/x.inft', base_dir=tmp_path, source=None, collector=collector)
    assert f is not None
    assert '~X' in f.read()
