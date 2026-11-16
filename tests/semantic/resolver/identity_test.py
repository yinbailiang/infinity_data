"""模板真名（依赖闭包组合哈希，§2.5）行为测试。

验证：
- 内容 + 依赖闭包相同 → 同身份（路径无关、跨文件去重）
- 内容相同但依赖不同 → 不同身份（``!from`` 按定义文件目录解析）
- 注释 / 空白不影响身份
- 循环依赖 → 终止且确定、可复现
"""

from __future__ import annotations

from pathlib import Path

from infinity_data import SandboxConfig
from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import DiskFile, MemFile
from infinity_data.sandbox import Sandbox
from infinity_data.semantic.resolver import ImportResolver, ResolvedContext, TemplateGraphResolver


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _make_resolver(base_dir: Path) -> TemplateGraphResolver:
    return TemplateGraphResolver(
        import_resolver=ImportResolver(
            sandbox=Sandbox(config=SandboxConfig(allow_templates=['**/*']), base_dir=base_dir)
        )
    )


def _ctx(source: str, *, name: str = 'app.infd', root: Path = Path('.')) -> tuple[ResolvedContext, DiagnosticCollector]:
    file = MemFile(name=name, root_path=root, content=source)
    doc, _ = parse_source(file)
    collector = DiagnosticCollector()
    ctx = TemplateGraphResolver().resolve(doc, file, collector)
    return ctx, collector


def _resolve_app(base: Path, source: str) -> tuple[ResolvedContext, DiagnosticCollector]:
    file = DiskFile.from_fullpath(base / 'app.infd')
    _write(Path(file.name), source)
    doc, _ = parse_source(file)
    collector = DiagnosticCollector()
    ctx = _make_resolver(base).resolve(doc, file, collector)
    return ctx, collector


def _identity_of(ctx: ResolvedContext, visible: str) -> str:
    return ctx.root_scope.visible[visible].identity


def _template_identity(ctx: ResolvedContext, name: str) -> str:
    return next(k.identity for k in ctx.templates if k.name == name)


# ═══════════════════════════════════════════════════════════
# 内容寻址：路径无关 / 内容敏感 / 注释无关
# ═══════════════════════════════════════════════════════════


def test_identity_path_independent() -> None:
    """同一内容 + 无依赖 → 同身份（与路径无关）。"""
    c1, _ = _ctx('~A {\n    a: int = 1\n}\n', name='x.infd', root=Path('/x'))
    c2, _ = _ctx('~A {\n    a: int = 1\n}\n', name='y.infd', root=Path('/y'))
    id1 = _identity_of(c1, 'A')
    id2 = _identity_of(c2, 'A')
    assert id1 == id2
    assert id1.startswith('h:')


def test_identity_content_sensitive() -> None:
    """内容不同 → 不同身份。"""
    c1, _ = _ctx('~A {\n    a: int = 1\n}\n')
    c2, _ = _ctx('~A {\n    a: int = 2\n}\n')
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')


def test_identity_ignores_comments_and_whitespace() -> None:
    """注释 / 尾逗号不影响身份（AST 规范化结构哈希）。"""
    c1, _ = _ctx('~A {\n    a: int = 1\n}\n')
    c2, _ = _ctx('~A {\n    # 注释行\n    a: int = 1,   # 尾注\n}\n')
    assert _identity_of(c1, 'A') == _identity_of(c2, 'A')


def test_identity_config_sensitive() -> None:
    """模板配置（allow_extra / positional）参与身份。"""
    c1, _ = _ctx('~A {\n    a: int = 1\n}\n')
    c2, _ = _ctx('~A(allow_extra=true) {\n    a: int = 1\n}\n')
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')


# ═══════════════════════════════════════════════════════════
# 依赖闭包：依赖不同 → 不同身份；依赖相同 → 同身份
# ═══════════════════════════════════════════════════════════


def test_identity_dependency_different(tmp_path: Path) -> None:
    """内容相同但依赖不同（!from 解析到不同内容的 Base）→ 不同身份。"""
    _write(tmp_path / 't1' / 'base.inft', '~Base {\n    id: int = 1\n}\n')
    _write(tmp_path / 't2' / 'base.inft', '~Base {\n    id: int = 2\n}\n')
    app = '!from p"base.inft" import Base\n~A {\n    b: Base = Base()\n}\n'
    c1, d1 = _resolve_app(tmp_path / 't1', app)
    c2, d2 = _resolve_app(tmp_path / 't2', app)
    assert not list(d1) and not list(d2)
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')


def test_identity_dependency_same(tmp_path: Path) -> None:
    """内容相同 + 依赖内容相同 → 同身份（跨路径去重）。"""
    _write(tmp_path / 't1' / 'base.inft', '~Base {\n    id: int = 1\n}\n')
    _write(tmp_path / 't2' / 'base.inft', '~Base {\n    id: int = 1\n}\n')
    app = '!from p"base.inft" import Base\n~A {\n    b: Base = Base()\n}\n'
    c1, d1 = _resolve_app(tmp_path / 't1', app)
    c2, d2 = _resolve_app(tmp_path / 't2', app)
    assert not list(d1) and not list(d2)
    assert _identity_of(c1, 'A') == _identity_of(c2, 'A')
    assert _template_identity(c1, 'Base') == _template_identity(c2, 'Base')


def test_identity_constraint_reference_dependency(tmp_path: Path) -> None:
    """模板即约束（约束中的模板名）也算依赖。"""
    _write(tmp_path / 't1' / 'base.inft', '~Base {\n    id: int = 1\n}\n')
    _write(tmp_path / 't2' / 'base.inft', '~Base {\n    id: int = 2\n}\n')
    app = '!from p"base.inft" import Base\n~A {\n    b: Base? = null\n}\n'
    c1, _ = _resolve_app(tmp_path / 't1', app)
    c2, _ = _resolve_app(tmp_path / 't2', app)
    # 约束里引用 Base（模板即约束）→ Base 不同 → A 不同
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')


# ═══════════════════════════════════════════════════════════
# 循环依赖：终止 / 确定 / 可复现
# ═══════════════════════════════════════════════════════════


def test_identity_circular_deterministic(tmp_path: Path) -> None:
    """循环导入（a ↔ b）：终止、确定、可复现。"""
    _write(tmp_path / 'a.inft', '!from p"b.inft" import B\n~A {\n    b: B = B()\n}\n')
    _write(tmp_path / 'b.inft', '!from p"a.inft" import A\n~B {\n    a: A? = null\n}\n')
    file = DiskFile.from_fullpath(tmp_path / 'app.infd')
    _write(Path(file.name), '!from p"a.inft" import A\nx = A()\n')
    doc, _ = parse_source(file)
    resolver = _make_resolver(tmp_path)
    c1 = resolver.resolve(doc, file, DiagnosticCollector())
    c2 = resolver.resolve(doc, file, DiagnosticCollector())
    ids1 = {k.identity for k in c1.templates}
    ids2 = {k.identity for k in c2.templates}
    assert ids1 == ids2  # 可复现
    assert len(ids1) == 2  # A、B 各自唯一身份（环内退化为内容 hash，仍互相区分）
    assert len({k.name for k in c1.templates}) == 2


# ═══════════════════════════════════════════════════════════
# 跨文件去重
# ═══════════════════════════════════════════════════════════


def test_identity_dedup_across_files(tmp_path: Path) -> None:
    """内容 + 依赖相同的模板（不同文件、不同可见名）→ 共享同一身份。"""
    _write(tmp_path / 'a' / 'extra.inft', '~Extra {\n    name: str = "x"\n}\n')
    _write(tmp_path / 'b' / 'extra.inft', '~Extra {\n    name: str = "x"\n}\n')
    app = '!from p"extra.inft" import Extra as E1\n!from p"extra.inft" import Extra as E2\n'
    file = DiskFile.from_fullpath(tmp_path / 'a' / 'app.infd')
    _write(Path(file.name), app)
    doc, _ = parse_source(file)
    resolver = _make_resolver(tmp_path / 'a')
    collector = DiagnosticCollector()
    ctx = resolver.resolve(doc, file, collector)
    assert not list(collector), [d.message for d in collector]
    k1 = ctx.root_scope.visible['E1']
    k2 = ctx.root_scope.visible['E2']
    assert k1.name == 'Extra' and k2.name == 'Extra'
    assert k1.identity == k2.identity  # 同内容同依赖 → 同身份
    # 同一身份只登记一次
    assert sum(1 for k in ctx.templates if k.identity == k1.identity) == 1


# ═══════════════════════════════════════════════════════════
# $ 数据依赖：导入真名纳入身份（§1.8 / §2.5）
# ═══════════════════════════════════════════════════════════


def test_identity_import_dependency_different() -> None:
    """内容相同的模板，$ 数据来源不同（!var 表达式不同）→ 不同身份。"""
    c1, _ = _ctx('!var 1 import . as x\n~A {\n    v: int = $x\n}\n')
    c2, _ = _ctx('!var 2 import . as x\n~A {\n    v: int = $x\n}\n')
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')


def test_identity_import_dependency_same() -> None:
    """内容 + $ 数据来源相同 → 同身份（可复现）。"""
    c1, _ = _ctx('!var 1 import . as x\n~A {\n    v: int = $x\n}\n')
    c2, _ = _ctx('!var 1 import . as x\n~A {\n    v: int = $x\n}\n')
    assert _identity_of(c1, 'A') == _identity_of(c2, 'A')


def test_identity_import_unused_does_not_affect() -> None:
    """模板不引用 $ 时，文件里的导入语句不影响其身份。"""
    c1, _ = _ctx('!var 1 import . as x\n~A {\n    v: int = 1\n}\n')
    c2, _ = _ctx('~A {\n    v: int = 1\n}\n')
    assert _identity_of(c1, 'A') == _identity_of(c2, 'A')


def test_identity_env_value_in_hash(tmp_path: Path) -> None:
    """!env 的**值**参与身份哈希：变量名相同、值不同 → 模板身份不同（环境漂移可见）。"""
    base = tmp_path
    app = '!env import PORT as port\n~A {\n    v: int = $port as int\n}\n'

    def resolve(name: str, port: str) -> ResolvedContext:
        return _resolve_with_env(base, name, app, {'PORT': port})

    c1 = resolve('app1.infd', '1')
    c2 = resolve('app2.infd', '9999')
    c3 = resolve('app3.infd', '1')
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')
    assert _identity_of(c1, 'A') == _identity_of(c3, 'A')  # 同值 → 同身份


def test_identity_env_value_propagates_through_var(tmp_path: Path) -> None:
    """!var 引用 env → env 取值变化经 var 真名传播到模板身份。"""
    base = tmp_path
    app = '!env import PORT as port\n!var $port import . as p\n~A {\n    v: str = $p\n}\n'
    c1 = _resolve_with_env(base, 'a.infd', app, {'PORT': '1'})
    c2 = _resolve_with_env(base, 'b.infd', app, {'PORT': '2'})
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')


def test_identity_var_chain_propagates_env(tmp_path: Path) -> None:
    """!var 链（p2 ← p1 ← env）逐级传递 env 取值。"""
    base = tmp_path
    app = '!env import PORT as port\n!var $port import . as p1\n!var $p1 import . as p2\n~A {\n    v: str = $p2\n}\n'
    c1 = _resolve_with_env(base, 'a.infd', app, {'PORT': '1'})
    c2 = _resolve_with_env(base, 'b.infd', app, {'PORT': '2'})
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')


def test_identity_file_value_propagates_through_var(tmp_path: Path) -> None:
    """!var 引用 !file → 文件内容变化经 var 真名传播到模板身份。"""
    _write(tmp_path / 't1' / 'data.json', '{"port": 1}')
    _write(tmp_path / 't2' / 'data.json', '{"port": 2}')
    app = '!file p"data.json" as json import .port as port\n!var $port import . as p\n~A {\n    v: int = $p\n}\n'
    c1, d1 = _resolve_app_full(tmp_path / 't1', app)
    c2, d2 = _resolve_app_full(tmp_path / 't2', app)
    assert not list(d1) and not list(d2)
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')


def test_identity_var_cycle_terminates(tmp_path: Path) -> None:
    """!var 相互引用（环）：真名计算终止且可复现（环上退化为自身表达式哈希）。"""
    app = '!var $b import . as a\n!var $a import . as b\n~A {\n    v: str = $a\n}\n'
    c1 = _resolve_with_env(tmp_path, 'a.infd', app, {})
    c2 = _resolve_with_env(tmp_path, 'b.infd', app, {})
    assert _identity_of(c1, 'A') == _identity_of(c2, 'A')


def _resolve_with_env(base: Path, name: str, app: str, env: dict[str, str]) -> ResolvedContext:
    """写文件 + 按注入 env 解析（identity 测试公用）。"""
    file = DiskFile.from_fullpath(base / name)
    _write(Path(file.name), app)
    doc, _ = parse_source(file)
    sb = Sandbox(SandboxConfig(env=env), base_dir=base)
    return TemplateGraphResolver(import_resolver=ImportResolver(sandbox=sb)).resolve(doc, file, DiagnosticCollector())


def _resolve_app_full(base: Path, source: str) -> tuple[ResolvedContext, DiagnosticCollector]:
    """同 _resolve_app，但 !file / !env 也授权（full_access 沙盒）。"""
    file = DiskFile.from_fullpath(base / 'app.infd')
    _write(Path(file.name), source)
    doc, _ = parse_source(file)
    collector = DiagnosticCollector()
    sb = Sandbox(SandboxConfig(allow_files=['**/*'], allow_templates=['**/*'], env={}), base_dir=base)
    ctx = TemplateGraphResolver(import_resolver=ImportResolver(sandbox=sb)).resolve(doc, file, collector)
    return ctx, collector


def test_identity_file_dependency_different(tmp_path: Path) -> None:
    """.inft 的 !file 内容不同 → 模板身份不同（导入真名含文件内容哈希）。"""
    _write(tmp_path / 't1' / 'data.json', '{"port": 1}')
    _write(tmp_path / 't2' / 'data.json', '{"port": 2}')
    app = '!file p"data.json" as json import .port as port\n~A {\n    v: int = $port\n}\n'
    c1, d1 = _resolve_app_full(tmp_path / 't1', app)
    c2, d2 = _resolve_app_full(tmp_path / 't2', app)
    assert not list(d1) and not list(d2)
    assert _identity_of(c1, 'A') != _identity_of(c2, 'A')


def test_identity_file_dependency_same(tmp_path: Path) -> None:
    """.inft 的 !file 内容相同 + 模板内容相同 → 同身份（可复现）。"""
    _write(tmp_path / 't1' / 'data.json', '{"port": 1}')
    _write(tmp_path / 't2' / 'data.json', '{"port": 1}')
    app = '!file p"data.json" as json import .port as port\n~A {\n    v: int = $port\n}\n'
    c1, d1 = _resolve_app_full(tmp_path / 't1', app)
    c2, d2 = _resolve_app_full(tmp_path / 't2', app)
    assert not list(d1) and not list(d2)
    assert _identity_of(c1, 'A') == _identity_of(c2, 'A')


def test_identity_file_denied_no_import_identity(tmp_path: Path) -> None:
    """.inft 的 !file 未授权 → 该 $ 绑定无导入真名 → 模板身份不纳入该数据依赖。"""
    _write(tmp_path / 'data.json', '{"port": 1}')
    app = '!file p"data.json" as json import .port as port\n~A {\n    v: int = $port\n}\n'
    file = DiskFile.from_fullpath(tmp_path / 'app.infd')
    _write(Path(file.name), app)
    doc, _ = parse_source(file)
    # 未授权 !file（strict=False → 返回 None，不抛）→ 无真名
    sb_denied = Sandbox(SandboxConfig(allow_templates=['**/*'], strict=False), base_dir=tmp_path)
    ctx_denied = TemplateGraphResolver(import_resolver=ImportResolver(sandbox=sb_denied)).resolve(
        doc, file, DiagnosticCollector()
    )
    # 授权 !file → 有真名
    sb_ok = Sandbox(SandboxConfig(allow_templates=['**/*'], allow_files=['**/*']), base_dir=tmp_path)
    ctx_ok = TemplateGraphResolver(import_resolver=ImportResolver(sandbox=sb_ok)).resolve(
        doc, file, DiagnosticCollector()
    )
    assert _identity_of(ctx_denied, 'A') != _identity_of(ctx_ok, 'A')
