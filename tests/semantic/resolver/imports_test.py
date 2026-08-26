"""semantic/resolver/imports.py 单元测试：ImportResolver 命名空间解析。"""

import sys
from pathlib import Path

import pytest

from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.builder.models import python_to_std
from infinity_data.semantic.resolver import ImportResolver


def _codes(collector: DiagnosticCollector) -> list[str]:
    return [d.code for d in collector]


def test_resolve_env_into_namespace() -> None:
    file = MemFile(name='t.infd', root_path=Path('.'), content='!env import USER\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(env={'USER': 'alice'}), base_dir=Path('.'))
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert ns['USER'] == python_to_std('alice')
    assert not list(collector)


def test_resolve_env_multi_import() -> None:
    """!env 一次导入多个变量（逗号分隔，as 别名可选）。"""
    file = MemFile(
        name='t.infd',
        root_path=Path('.'),
        content='!env import USER as u, HOME, PORT as p\n',
    )
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(env={'USER': 'alice', 'HOME': '/home/alice', 'PORT': '8080'}), base_dir=Path('.'))
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert ns['u'] == python_to_std('alice')
    assert ns['HOME'] == python_to_std('/home/alice')
    assert ns['p'] == python_to_std('8080')
    assert not list(collector)


def test_resolve_env_multi_import_duplicate_binds_first() -> None:
    """多导入中同一别名重复 → namespace.duplicate 错误，保留先到者。"""
    file = MemFile(name='t.infd', root_path=Path('.'), content='!env import USER as u, HOME as u\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(env={'USER': 'alice', 'HOME': '/home/alice'}), base_dir=Path('.'))
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert ns['u'] == python_to_std('alice')
    assert 'namespace.duplicate' in _codes(collector)


def test_resolve_env_duplicate_binds_first() -> None:
    file = MemFile(name='t.infd', root_path=Path('.'), content='!env import USER\n!env import USER\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(env={'USER': 'alice'}), base_dir=Path('.'))
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert ns['USER'] == python_to_std('alice')
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


def test_resolve_file_raw_explicit(tmp_path: Path) -> None:
    """raw：显式 as raw → 文件原文整体绑定为字符串（不解析）。"""
    (tmp_path / 'seed.txt').write_text('a\nb\n', encoding='utf-8')
    file = MemFile(name='t.infd', root_path=tmp_path, content='!file p"seed.txt" as raw import . as seed\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(allow_files=['./seed.txt']), base_dir=tmp_path)
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert ns['seed'] == python_to_std('a\nb\n')
    assert not list(collector)


def test_resolve_file_raw_suffix_detection(tmp_path: Path) -> None:
    """raw：无 as 时按后缀检测（.md → raw）。"""
    (tmp_path / 'README.md').write_text('# hi\n', encoding='utf-8')
    file = MemFile(name='t.infd', root_path=tmp_path, content='!file p"README.md" import . as readme\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(allow_files=['./README.md']), base_dir=tmp_path)
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert ns['readme'] == python_to_std('# hi\n')
    assert not list(collector)


def test_resolve_file_raw_path_on_string_warns(tmp_path: Path) -> None:
    """raw：对字符串应用非空 path → import.path_failed 警告（不中断）。"""
    (tmp_path / 'seed.txt').write_text('data', encoding='utf-8')
    file = MemFile(name='t.infd', root_path=tmp_path, content='!file p"seed.txt" as raw import .x as x\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(allow_files=['./seed.txt']), base_dir=tmp_path)
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert 'x' not in ns
    assert [d.code for d in collector] == ['import.path_failed']


def test_sandbox_properties() -> None:
    """sandbox / base_dir property 透传。"""
    sb = Sandbox(SandboxConfig.deny_all(), base_dir=Path('/x'))
    r = ImportResolver(sandbox=sb)
    assert r.sandbox is sb
    assert r.base_dir == Path('/x')


def test_import_identities_env_and_var() -> None:
    """import_identities：env/var 的来源哈希（确定性，与值无关）。"""
    file = MemFile(
        name='t.infd', root_path=Path('.'), content='!env import PORT as port\n!var 42 import .timeout as t\n'
    )
    doc, _ = parse_source(file)
    r = ImportResolver()
    ids1 = r.import_identities(doc)
    ids2 = r.import_identities(doc)
    assert set(ids1) == {'port', 't'}
    assert ids1 == ids2  # 确定性
    assert all(v.startswith('h') is False for v in ids1.values())  # 是十六进制哈希串


def test_import_identities_toml_file(tmp_path: Path) -> None:
    """import_identities：!file 来源哈希含文件内容（内容变 → 真名变）。"""
    (tmp_path / 'data.toml').write_text('port = 1\n', encoding='utf-8')
    file = MemFile(name='t.infd', root_path=tmp_path, content='!file p"data.toml" as toml import .port as p\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(allow_files=['./data.toml']), base_dir=tmp_path)
    r = ImportResolver(sandbox=sb)
    ids1 = r.import_identities(doc)
    (tmp_path / 'data.toml').write_text('port = 2\n', encoding='utf-8')
    ids2 = r.import_identities(doc)
    assert ids1['p'] != ids2['p']


def test_parse_data_yaml_missing_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PyYAML 缺失 → import.yaml_missing 警告（import yaml 抛 ImportError）。"""
    monkeypatch.setitem(sys.modules, 'yaml', None)  # sys.modules 中 None → import 抛 ImportError
    (tmp_path / 'data.yaml').write_text('a: 1\n', encoding='utf-8')
    file = MemFile(name='t.infd', root_path=tmp_path, content='!file p"data.yaml" as yaml import .a as a\n')
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(allow_files=['./data.yaml']), base_dir=tmp_path)
    collector = DiagnosticCollector()
    ns = ImportResolver(sandbox=sb).resolve(doc, collector)
    assert 'a' not in ns
    assert [d.code for d in collector] == ['import.yaml_missing']
