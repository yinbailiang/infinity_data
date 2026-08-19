"""Phase 1 导入解析器（TemplateGraphResolver）独立测试。

只测「名字解析 + 模板图构建」，不涉及约束执行——约束求值属 Phase 2
（AstBuilder / ConstraintExecutor），此处明确验证 Phase 1 不含约束执行。
"""

from __future__ import annotations

from pathlib import Path

from infinity_data import SandboxConfig
from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import DiskFile, MemFile
from infinity_data.parser.models import Document
from infinity_data.sandbox import Sandbox
from infinity_data.semantic.resolver import ImportResolver, ResolvedContext, TemplateGraphResolver


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _make_resolver(
    base_dir: Path,
    config: SandboxConfig | None = None,
    parse_cache: dict[str, Document] | None = None,
) -> TemplateGraphResolver:
    return TemplateGraphResolver(
        import_resolver=ImportResolver(sandbox=Sandbox(config=config or SandboxConfig.deny_all(), base_dir=base_dir)),
        parse_cache=parse_cache,
    )


def _resolve_text(source: str) -> tuple[ResolvedContext, DiagnosticCollector]:
    file = MemFile(name='app.infd', root_path=Path('.'), content=source)
    doc, _ = parse_source(file)
    collector = DiagnosticCollector()
    ctx = TemplateGraphResolver().resolve(doc, file, collector)
    return ctx, collector


def _codes(collector: DiagnosticCollector) -> list[str]:
    return [d.code for d in collector]


# ═══════════════════════════════════════════════════════════
# 模板收集与 scope
# ═══════════════════════════════════════════════════════════


def test_resolve_collects_local_templates() -> None:
    ctx, collector = _resolve_text('~A {\n    a: int = 1\n}\nx = 1\n')
    assert not list(collector)
    # root_scope：本地模板可见名 → TemplateKey
    assert 'A' in ctx.root_scope
    key = ctx.root_scope['A']
    assert key.name == 'A'
    assert key in ctx.templates
    # 模板定义点 scope 已登记
    assert ctx.template_scopes[key] is ctx.root_scope
    # 无数据导入 → 空命名空间
    assert ctx.namespace == {}


def test_resolve_shadowing_builtin_diagnostic() -> None:
    """~str 遮蔽内置约束 → ERROR；被拒模板不入表（内置 str 保持可用）。"""
    ctx, collector = _resolve_text('~str {\n    v: str = "x"\n}\n')
    assert 'template.shadows_builtin' in _codes(collector)
    assert not any(k.name == 'str' for k in ctx.templates)


def test_resolve_duplicate_local_template() -> None:
    """同名模板重复定义 → ERROR，保留首次定义。"""
    ctx, collector = _resolve_text('~A {\n    a: int = 1\n}\n~A {\n    b: int = 2\n}\n')
    assert 'template.duplicate' in _codes(collector)
    matches = [k for k in ctx.templates if k.name == 'A']
    assert len(matches) == 1
    assert ctx.templates[matches[0]].fields[0].name == 'a'  # 保留先到者


def test_resolve_does_not_execute_constraints() -> None:
    """Phase 1 只做导入解析，不执行约束——字段约束错误不在 context 诊断中。"""
    _, collector = _resolve_text('x: int = "not-an-int"\n')
    assert not list(collector)  # constraint.* 诊断只会在 Phase 2 出现


# ═══════════════════════════════════════════════════════════
# 模板导入（!from）
# ═══════════════════════════════════════════════════════════


def test_resolve_imported_template_scope(tmp_path: Path) -> None:
    _write(tmp_path / 'templates' / 'extra.inft', '~Extra {\n    name: str = "x"\n}\n')
    file = DiskFile.from_fullpath(tmp_path / 'app.infd')
    _write(Path(file.name), '!from "templates/extra.inft" import Extra\nval = Extra()\n')
    doc, _ = parse_source(file)
    resolver = _make_resolver(tmp_path, SandboxConfig(allow_templates=['./templates/*.inft']))
    collector = DiagnosticCollector()
    ctx = resolver.resolve(doc, file, collector)
    assert not list(collector), [d.message for d in collector]
    # 可见名 Extra → 导入模板的 TemplateKey
    assert 'Extra' in ctx.root_scope
    key = ctx.root_scope['Extra']
    assert key.name == 'Extra'
    assert key in ctx.templates
    assert ctx.templates[key].fields[0].name == 'name'


def test_resolve_circular_import_guard(tmp_path: Path) -> None:
    """a ↔ b 互相导入：不无限递归，两模板都进表。"""
    _write(tmp_path / 'a.inft', '!from "b.inft" import B\n~A {\n    b: B = B()\n}\n')
    _write(tmp_path / 'b.inft', '!from "a.inft" import A\n~B {\n    a: A? = null\n}\n')
    file = DiskFile.from_fullpath(tmp_path / 'app.infd')
    _write(Path(file.name), '!from "a.inft" import A\nx = A()\n')
    doc, _ = parse_source(file)
    resolver = _make_resolver(tmp_path, SandboxConfig(allow_templates=['**/*']))
    collector = DiagnosticCollector()
    ctx = resolver.resolve(doc, file, collector)
    assert not list(collector), [d.message for d in collector]
    assert 'A' in ctx.root_scope
    assert {'A', 'B'} <= {k.name for k in ctx.templates}


def test_resolve_nested_import_mapping(tmp_path: Path) -> None:
    """嵌套导入：导入文件的 !from 也解析进该文件的 scope。"""
    _write(tmp_path / 'base.inft', '~Base {\n    id: int = 0\n}\n')
    _write(tmp_path / 'mid.inft', '!from "base.inft" import Base\n~Mid {\n    base: Base = Base()\n}\n')
    file = DiskFile.from_fullpath(tmp_path / 'app.infd')
    _write(Path(file.name), '!from "mid.inft" import Mid\nm = Mid()\n')
    doc, _ = parse_source(file)
    resolver = _make_resolver(tmp_path, SandboxConfig(allow_templates=['**/*']))
    collector = DiagnosticCollector()
    ctx = resolver.resolve(doc, file, collector)
    assert not list(collector), [d.message for d in collector]
    assert {'Mid', 'Base'} <= {k.name for k in ctx.templates}


# ═══════════════════════════════════════════════════════════
# 数据导入（!env / !file）命名空间
# ═══════════════════════════════════════════════════════════


def test_resolve_env_namespace() -> None:
    file = MemFile(
        name='app.infd', root_path=Path('.'), content='!env import INF_RESOLVER_KEY\nv = $INF_RESOLVER_KEY\n'
    )
    doc, _ = parse_source(file)
    resolver = _make_resolver(Path('.'), SandboxConfig(env={'INF_RESOLVER_KEY': 'ok'}))
    collector = DiagnosticCollector()
    ctx = resolver.resolve(doc, file, collector)
    assert not list(collector)
    assert ctx.namespace == {'INF_RESOLVER_KEY': 'ok'}


# ═══════════════════════════════════════════════════════════
# 幂等与缓存
# ═══════════════════════════════════════════════════════════


def test_resolve_idempotent() -> None:
    resolver = TemplateGraphResolver()
    file = MemFile(name='app.infd', root_path=Path('.'), content='~A {\n    a: int = 1\n}\nx = 1\n')
    doc, _ = parse_source(file)
    c1 = resolver.resolve(doc, file, DiagnosticCollector())
    c2 = resolver.resolve(doc, file, DiagnosticCollector())
    assert set(c1.templates) == set(c2.templates)
    assert c1.root_scope == c2.root_scope
    assert c1.namespace == c2.namespace


def test_parse_cache_reuse(tmp_path: Path) -> None:
    """parse_cache 跨 resolve 复用：文件内容变化后仍返回缓存（跳过重解析）。"""
    cache: dict[str, Document] = {}
    tpl_file = DiskFile.from_fullpath(tmp_path / 'tpl.inft')
    _write(Path(tpl_file.name), '~T {\n    a: int = 1\n}\n')
    app = DiskFile.from_fullpath(tmp_path / 'app.infd')
    _write(Path(app.name), '!from "tpl.inft" import T\n')
    doc, _ = parse_source(app)
    resolver = _make_resolver(tmp_path, SandboxConfig(allow_templates=['**/*']), parse_cache=cache)

    c1 = resolver.resolve(doc, app, DiagnosticCollector())
    assert 'T' in c1.root_scope
    assert tpl_file.identity in cache  # 导入文件解析结果已入缓存

    # 修改模板文件内容；缓存命中 → 仍返回旧定义（字段 a）
    _write(Path(tpl_file.name), '~T {\n    b: int = 2\n}\n')
    c2 = resolver.resolve(doc, app, DiagnosticCollector())
    key = c2.root_scope['T']
    assert c2.templates[key].fields[0].name == 'a'
