"""M3 安全模型测试：sandbox 授权、safe_load、!from 模板导入、顶层 schema 约束。"""

from __future__ import annotations

from pathlib import Path

import pytest

from infinity_data import (
    SandboxConfig,
    SandboxError,
    Schema,
    SchemaError,
    check,
    compile_source,
    compile_to_dict,
    load,
    safe_load,
)
from infinity_data.semantic.models import Severity


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


# ═══════════════════════════════════════════════════════
# safe_load / 零信任默认
# ═══════════════════════════════════════════════════════


def test_safe_load_pure_data(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, 'name = "demo"\nport = 8080\n')
    result = safe_load(f)
    assert not result.has_errors
    assert result.value == {'name': 'demo', 'port': 8080}


def test_safe_load_rejects_env_import(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\nuser = $USER\n')
    with pytest.raises(SandboxError):
        safe_load(f)


def test_load_default_is_deny_all(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!file "data.json" import .key as k\nvalue = $k\n')
    with pytest.raises(SandboxError):
        load(f)


def test_env_import_requires_authorization(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\nuser = $USER\n')
    with pytest.raises(SandboxError):
        load(f)  # 默认零信任
    result = load(f, sandbox=SandboxConfig(env={'USER': 'alice'}))
    assert result.value == {'user': 'alice'}


def test_env_param_is_convenience_authorization(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\nuser = $USER\n')
    result = load(f, env={'USER': 'alice'})
    assert result.value == {'user': 'alice'}


def test_non_strict_sandbox_warns_instead_of_raise(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\nuser = $USER\n')
    result = load(f, sandbox=SandboxConfig(strict=False))
    assert not result.has_errors
    assert any(d.severity is Severity.WARNING for d in result.diagnostics)


def test_file_import_unauthorized_raises(tmp_path: Path) -> None:
    data = tmp_path / 'data.json'
    _write(data, '{"key": 42}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "data.json" import .key as k\nvalue = $k\n')
    with pytest.raises(SandboxError):
        load(f, sandbox=SandboxConfig(allow_files=['./other/*.json']))
    result = load(f, sandbox=SandboxConfig(allow_files=['./data.json']))
    assert result.value == {'value': 42}


def test_check_does_not_raise(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\nuser = $USER\n')
    diagnostics = check(f)  # 默认零信任 → 违规转 ERROR 诊断
    assert diagnostics
    assert all(d.severity is Severity.ERROR for d in diagnostics)


# ═══════════════════════════════════════════════════════
# !from 模板导入
# ═══════════════════════════════════════════════════════


def test_template_import_from_inft(tmp_path: Path) -> None:
    tpl = tmp_path / 'templates' / 'extra.inft'
    _write(tpl, '~Extra {\n    name: str = "x"\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '!from "templates/extra.inft" import Extra\nval = Extra(name="y")\n')
    result = load(f, sandbox=SandboxConfig(allow_templates=['./templates/*.inft']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'val': {'name': 'y'}}


def test_template_import_with_alias(tmp_path: Path) -> None:
    """!from ... import Name as Alias：别名可用，原名保留。"""
    tpl = tmp_path / 'templates' / 'extra.inft'
    _write(tpl, '~Extra {\n    name: str = "x"\n}\n')
    f = tmp_path / 'app.infd'
    _write(
        f,
        '!from "templates/extra.inft" import Extra as Ex\na = Ex(name="y")\nb = Extra(name="z")\n',
    )
    result = load(f, sandbox=SandboxConfig(allow_templates=['./templates/*.inft']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'a': {'name': 'y'}, 'b': {'name': 'z'}}


def test_template_import_multiple_with_mixed_alias(tmp_path: Path) -> None:
    tpl = tmp_path / 'extra.inft'
    _write(tpl, '~A {\n    x: int = 1\n}\n~B {\n    y: str = "b"\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '!from "extra.inft" import A as A1, B\nv = A1()\nw = B()\n')
    result = load(f, sandbox=SandboxConfig.development())
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'v': {'x': 1}, 'w': {'y': 'b'}}


def test_template_import_alias_conflict_with_local(tmp_path: Path) -> None:
    tpl = tmp_path / 'extra.inft'
    _write(tpl, '~Server {\n    host: str = "0.0.0.0"\n}\n')
    f = tmp_path / 'app.infd'
    _write(
        f,
        '~MyServer {\n    port: int = 80\n}\n!from "extra.inft" import Server as MyServer\n',
    )
    result = load(f, sandbox=SandboxConfig.development())
    assert result.has_errors
    assert any('冲突' in d.message for d in result.diagnostics)


def test_template_import_alias_missing_source(tmp_path: Path) -> None:
    tpl = tmp_path / 'extra.inft'
    _write(tpl, '~Extra {\n    name: str = "x"\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '!from "extra.inft" import DoesNotExist as X\n')
    result = load(f, sandbox=SandboxConfig.development())
    assert result.has_errors
    assert any('不存在' in d.message for d in result.diagnostics)


def test_template_import_nested(tmp_path: Path) -> None:
    base = tmp_path / 'templates' / 'base.inft'
    _write(base, '~Base {\n    id: int = 0\n}\n')
    mid = tmp_path / 'templates' / 'mid.inft'
    _write(mid, '!from "base.inft" import Base\n~Mid {\n    base: Base = Base()\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '!from "templates/mid.inft" import Mid\nm = Mid(base=Base(id=7))\n')
    result = load(f, sandbox=SandboxConfig.development())
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'m': {'base': {'id': 7}}}


def test_template_import_unauthorized_raises(tmp_path: Path) -> None:
    tpl = tmp_path / 'templates' / 'extra.inft'
    _write(tpl, '~Extra {\n    name: str = "x"\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '!from "templates/extra.inft" import Extra\nval = Extra()\n')
    with pytest.raises(SandboxError):
        load(f, sandbox=SandboxConfig(allow_templates=['./allowed/*.inft']))


def test_template_import_conflict_with_local(tmp_path: Path) -> None:
    tpl = tmp_path / 'extra.inft'
    _write(tpl, '~Server {\n    host: str = "0.0.0.0"\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '~Server {\n    port: int = 80\n}\n!from "extra.inft" import Server\n')
    result = load(f, sandbox=SandboxConfig.development())
    assert result.has_errors
    assert any('冲突' in d.message for d in result.diagnostics)


def test_template_import_cyclic_is_safe(tmp_path: Path) -> None:
    a = tmp_path / 'a.inft'
    _write(a, '!from "b.inft" import B\n~A {\n    b: B = B()\n}\n')
    b = tmp_path / 'b.inft'
    _write(b, '!from "a.inft" import A\n~B {\n    a: A? = null\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '!from "a.inft" import A\nx = A()\n')
    result = load(f, sandbox=SandboxConfig.development())
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'x': {'b': {'a': None}}}


# ═══════════════════════════════════════════════════════
# 顶层 schema 约束
# ═══════════════════════════════════════════════════════


def _app_config(tmp_path: Path) -> Path:
    f = tmp_path / 'app.infd'
    _write(
        f,
        '~AppConfig {\n    name: str\n    port: int = 8080\n}\nname = "demo"\nport = 9090\n',
    )
    return f


def test_schema_strict_passes(tmp_path: Path) -> None:
    result = load(_app_config(tmp_path), schema=Schema(template='AppConfig'))
    assert not result.has_errors
    assert result.value == {'name': 'demo', 'port': 9090}


def test_schema_strict_missing_required(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '~AppConfig {\n    name: str\n}\n')
    with pytest.raises(SchemaError):
        load(f, schema=Schema(template='AppConfig'))


def test_schema_strict_extra_field_raises(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '~AppConfig {\n    name: str = "x"\n}\nname = "x"\nextra = 1\n')
    with pytest.raises(SchemaError):
        load(f, schema=Schema(template='AppConfig', mode='strict'))


def test_schema_lenient_extra_field_warns(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '~AppConfig {\n    name: str = "x"\n}\nname = "x"\nextra = 1\n')
    result = load(f, schema=Schema(template='AppConfig', mode='lenient'))
    assert not result.has_errors
    assert any(d.severity is Severity.WARNING for d in result.diagnostics)
    assert result.value == {'name': 'x', 'extra': 1}


def test_schema_strip_extra_field_removed(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '~AppConfig {\n    name: str = "x"\n}\nname = "x"\nextra = 1\n')
    result = load(f, schema=Schema(template='AppConfig', mode='strip'))
    assert not result.has_errors
    assert result.value == {'name': 'x'}


def test_schema_from_file(tmp_path: Path) -> None:
    tpl = tmp_path / 'templates' / 'AppConfig.inft'
    _write(tpl, '~AppConfig {\n    name: str\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, 'name = "demo"\n')
    result = load(
        f,
        sandbox=SandboxConfig(allow_templates=['./templates/*.inft']),
        schema=Schema(template='AppConfig', from_file='templates/AppConfig.inft'),
    )
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'name': 'demo'}


def test_schema_field_constraint_violation(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '~AppConfig {\n    port: <int, range(1, 100)> = 80\n}\nport = 200\n')
    with pytest.raises(SchemaError):
        load(f, schema=Schema(template='AppConfig'))


# ═══════════════════════════════════════════════════════
# 自举：SandboxConfig.from_dict + compile_to_dict
# ═══════════════════════════════════════════════════════


def test_sandbox_config_from_dict_bootstrap(tmp_path: Path) -> None:
    sandbox_def = tmp_path / 'sandbox.infd'
    _write(
        sandbox_def,
        'env = { USER = "alice" }\nallow_files ["./configs/*.json"]\nstrict = true\n',
    )
    sb = SandboxConfig.from_dict(safe_load(sandbox_def).value)
    assert sb.env == {'USER': 'alice'}
    assert sb.allow_files == ['./configs/*.json']
    assert sb.strict is True


def test_compile_to_dict(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, 'name = "demo"\n')
    doc = compile_to_dict(f)
    assert doc.root.get('name') is not None
    assert not doc.has_errors


def test_compile_source_with_schema(tmp_path: Path) -> None:
    src = '~AppConfig {\n    name: str\n}\nname = "demo"\n'
    result = compile_source(src, schema=Schema(template='AppConfig'))
    assert not result.has_errors
    assert result.value == {'name': 'demo'}


def test_full_access_sandbox(tmp_path: Path) -> None:
    data = tmp_path / 'data.json'
    _write(data, '{"key": 1}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "data.json" import .key as k\nv = $k\n')
    result = load(f, sandbox=SandboxConfig.full_access())
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'v': 1}
