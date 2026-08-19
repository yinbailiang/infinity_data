"""M3 安全模型测试：sandbox 授权、safe_load、!from 模板导入、顶层 schema 约束。"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from infinity_data import (
    SandboxConfig,
    Schema,
    check,
    compile_document,
    compile_source,
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
    result = safe_load(f)
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['sandbox.env_unauthorized']
    assert result.value == {}  # 沙盒违规 → 空文档


def test_load_default_is_deny_all(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!file "data.json" import .key as k\nvalue = $k\n')
    result = load(f)
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['sandbox.access_denied']
    assert result.value == {}


def test_env_import_requires_authorization(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\nuser = $USER\n')
    denied = load(f)  # 默认零信任 → 违规转为 ERROR 诊断
    assert denied.has_errors
    assert [d.code for d in denied.diagnostics] == ['sandbox.env_unauthorized']
    assert denied.value == {}
    result = load(f, sandbox=SandboxConfig(env={'USER': 'alice'}))
    assert result.value == {'user': 'alice'}


def test_env_param_is_convenience_authorization(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\nuser = $USER\n')
    result = load(f, env={'USER': 'alice'})
    assert result.value == {'user': 'alice'}


# ═══════════════════════════════════════════════════════
# $ 引用类型转换（as bool / int / float / str）
# ═══════════════════════════════════════════════════════


def test_dollar_cast_int(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!env import PORT\nport = $PORT as int\n')
    result = load(f, env={'PORT': '8080'})
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'port': 8080}


def test_dollar_cast_bool(tmp_path: Path) -> None:
    """as bool：true/1 → true，其余（含 false/0/其他串）→ false，不分大小写。"""
    f = tmp_path / 'app.infd'
    _write(f, '!env import A\n!env import B\n!env import C\na = $A as bool\nb = $B as bool\nc = $C as bool\n')
    result = load(f, env={'A': 'True', 'B': '0', 'C': 'yes'})
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'a': True, 'b': False, 'c': False}


def test_dollar_cast_float(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '!env import R\nr = $R as float\n')
    result = load(f, env={'R': '1.5'})
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'r': Decimal('1.5')}


def test_dollar_cast_str_and_plain(tmp_path: Path) -> None:
    """as str 原样；无 as 时不转换（字符串保持字符串）。"""
    f = tmp_path / 'app.infd'
    _write(f, '!env import NAME\ns = $NAME as str\nplain = $NAME\n')
    result = load(f, env={'NAME': 'demo'})
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'s': 'demo', 'plain': 'demo'}


def test_dollar_cast_failure_warns_and_falls_back(tmp_path: Path) -> None:
    """转换失败 → dollar.convert_failed 警告 + 回退 0（不构成错误）。"""
    f = tmp_path / 'app.infd'
    _write(f, '!env import BAD\nx = $BAD as int\n')
    result = load(f, env={'BAD': 'not-a-number'})
    assert not result.has_errors
    assert any(d.code == 'dollar.convert_failed' for d in result.diagnostics)
    assert result.value == {'x': 0}


def test_env_authorized_read_from_os(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """allow_env 授权从真实 OS 环境实时读取（非注入快照）。"""
    monkeypatch.setenv('INF_DEMO_KEY', 'from-os')
    f = tmp_path / 'app.infd'
    _write(f, '!env import INF_DEMO_KEY\nv = $INF_DEMO_KEY\n')
    result = load(f, sandbox=SandboxConfig(allow_env=['INF_DEMO_KEY']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'v': 'from-os'}


def test_env_authorized_but_not_set_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """已授权但进程未设置 → 失败（不注入空值）。"""
    monkeypatch.delenv('INF_NOT_SET', raising=False)
    f = tmp_path / 'app.infd'
    _write(f, '!env import INF_NOT_SET\nv = $INF_NOT_SET\n')
    result = load(f, sandbox=SandboxConfig(allow_env=['INF_NOT_SET']))
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['sandbox.env_not_set']
    assert result.value == {}


def test_env_injection_takes_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注入值（env）优先于 allow_env 的真实读取。"""
    monkeypatch.setenv('INF_DUP', 'from-os')
    f = tmp_path / 'app.infd'
    _write(f, '!env import INF_DUP\nv = $INF_DUP\n')
    result = load(f, sandbox=SandboxConfig(env={'INF_DUP': 'injected'}, allow_env=['INF_DUP']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'v': 'injected'}


def test_full_access_reads_live_os_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """full_access 授权全部环境变量，值实时来自 OS（非构造时快照）。"""
    monkeypatch.setenv('INF_LIVE', 'live-value')
    f = tmp_path / 'app.infd'
    _write(f, '!env import INF_LIVE\nv = $INF_LIVE\n')
    result = load(f, sandbox=SandboxConfig.full_access())
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'v': 'live-value'}


def test_allow_env_not_authorized_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """allow_env 白名单外的变量仍失败。"""
    monkeypatch.setenv('INF_OUTSIDE', 'secret')
    f = tmp_path / 'app.infd'
    _write(f, '!env import INF_OUTSIDE\nv = $INF_OUTSIDE\n')
    result = load(f, sandbox=SandboxConfig(allow_env=['INF_OTHER']))
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['sandbox.env_unauthorized']
    assert result.value == {}


def test_non_strict_env_import_still_fails(tmp_path: Path) -> None:
    """env 未授权总是失败：非 strict 也不例外（不静默退化为空串）。"""
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\nuser = $USER\n')
    result = load(f, sandbox=SandboxConfig(strict=False))
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['sandbox.env_unauthorized']
    assert result.value == {}


def test_file_import_unauthorized_denied(tmp_path: Path) -> None:
    data = tmp_path / 'data.json'
    _write(data, '{"key": 42}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "data.json" import .key as k\nvalue = $k\n')
    denied = load(f, sandbox=SandboxConfig(allow_files=['./other/*.json']))
    assert denied.has_errors
    assert [d.code for d in denied.diagnostics] == ['sandbox.access_denied']
    assert denied.value == {}
    result = load(f, sandbox=SandboxConfig(allow_files=['./data.json']))
    assert result.value == {'value': 42}


def test_file_import_whole_file(tmp_path: Path) -> None:
    """整文件导入：!file ... import . as all → $all 为整个结构（. 后接 as 不视为路径段）。"""
    data = tmp_path / 'data.json'
    _write(data, '{"host": "example.com", "port": 443}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "data.json" as json import . as all\nv = $all\n')
    result = load(f, sandbox=SandboxConfig(allow_files=['./data.json']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'v': {'host': 'example.com', 'port': 443}}


def test_file_import_first_segment_as_key(tmp_path: Path) -> None:
    """根键名为 as：首段标识符 as 保留给整文件别名，须用字符串段 ."as"。"""
    data = tmp_path / 'data.json'
    _write(data, '{"as": {"v": 1}, "as2": 2}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "data.json" as json import ."as" as v\nx = $v\n')
    result = load(f, sandbox=SandboxConfig(allow_files=['./data.json']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'x': {'v': 1}}


# ═══════════════════════════════════════════════════════
# glob 白名单匹配
# ═══════════════════════════════════════════════════════


def test_glob_double_star_matches_nested(tmp_path: Path) -> None:
    """** 跨任意深度匹配嵌套文件。"""
    data = tmp_path / 'configs' / 'dev' / 'data.json'
    _write(data, '{"key": 42}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "configs/dev/data.json" import .key as k\nvalue = $k\n')
    result = load(f, sandbox=SandboxConfig(allow_files=['**/*.json']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'value': 42}


def test_glob_double_star_matches_root_level(tmp_path: Path) -> None:
    """** 匹配零段：**/*.json 也能命中根级文件。"""
    data = tmp_path / 'data.json'
    _write(data, '{"key": 7}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "data.json" import .key as k\nvalue = $k\n')
    result = load(f, sandbox=SandboxConfig(allow_files=['**/*.json']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'value': 7}


def test_glob_dir_double_star_matches_nested(tmp_path: Path) -> None:
    """configs/** 匹配其下任意深度文件。"""
    data = tmp_path / 'configs' / 'dev' / 'data.json'
    _write(data, '{"key": 1}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "configs/dev/data.json" import .key as k\nvalue = $k\n')
    result = load(f, sandbox=SandboxConfig(allow_files=['configs/**']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'value': 1}


def test_glob_single_star_does_not_cross_separator(tmp_path: Path) -> None:
    """* 不跨目录分隔符：configs/*.json 不匹配嵌套文件。"""
    data = tmp_path / 'configs' / 'dev' / 'data.json'
    _write(data, '{"key": 1}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "configs/dev/data.json" import .key as k\nvalue = $k\n')
    result = load(f, sandbox=SandboxConfig(allow_files=['configs/*.json']))
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['sandbox.access_denied']
    assert result.value == {}


def test_glob_single_star_matches_one_level(tmp_path: Path) -> None:
    """* 匹配一层路径：configs/*.json 命中 configs/data.json。"""
    data = tmp_path / 'configs' / 'data.json'
    _write(data, '{"key": 5}')
    f = tmp_path / 'app.infd'
    _write(f, '!file "configs/data.json" import .key as k\nvalue = $k\n')
    result = load(f, sandbox=SandboxConfig(allow_files=['configs/*.json']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'value': 5}


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


def test_imported_template_shadowing_builtin_is_error(tmp_path: Path) -> None:
    """导入文件中的 ~str 与内置约束同名 → ERROR，内置 str 不被遮蔽。"""
    tpl = tmp_path / 'bad.inft'
    _write(tpl, '~str {\n    v: str = "x"\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '!from "bad.inft" import str\ns: str = "ok"\n')
    result = load(f, sandbox=SandboxConfig.development())
    assert result.has_errors
    assert any(d.code == 'template.shadows_builtin' for d in result.diagnostics)
    # 内置 str 保持可用
    assert result.value == {'s': 'ok'}


def test_duplicate_import_visible_name_is_error(tmp_path: Path) -> None:
    """两个导入映射到同一可见名 → ERROR，保留首个映射（拒绝隐式覆盖）。"""
    _write(tmp_path / 'a.inft', '~Server {\n    a: int = 1\n}\n')
    _write(tmp_path / 'b.inft', '~Server {\n    b: int = 2\n}\n')
    f = tmp_path / 'app.infd'
    _write(
        f,
        '!from "a.inft" import Server\n!from "b.inft" import Server\ns = Server()\n',
    )
    result = load(f, sandbox=SandboxConfig.development())
    assert result.has_errors
    assert any(d.code == 'template.import_duplicate' for d in result.diagnostics)
    # 首个可见名映射被保留（a.inft 的 Server）
    assert result.value == {'s': {'a': 1}}


def test_duplicate_env_alias_is_error(tmp_path: Path) -> None:
    """$ 命名空间重复 env alias → ERROR，保留先到者。"""
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\n!env import HOME as USER\nuser = $USER\n')
    result = load(f, sandbox=SandboxConfig(env={'USER': 'alice', 'HOME': '/home/alice'}))
    assert result.has_errors
    assert any(d.code == 'namespace.duplicate' for d in result.diagnostics)
    # 先到者生效：$USER = alice
    assert result.value == {'user': 'alice'}


def test_duplicate_alias_env_and_file_is_error(tmp_path: Path) -> None:
    """env 与 file 绑定同一 alias → ERROR，保留先到者。"""
    data = tmp_path / 'data.json'
    _write(data, '{"key": "from-file"}')
    f = tmp_path / 'app.infd'
    _write(f, '!env import USER\n!file "data.json" import .key as USER\nv = $USER\n')
    result = load(
        f,
        sandbox=SandboxConfig(env={'USER': 'alice'}, allow_files=['./data.json']),
    )
    assert result.has_errors
    assert any(d.code == 'namespace.duplicate' for d in result.diagnostics)
    # 先到者生效：$USER = alice（env 在前）
    assert result.value == {'v': 'alice'}


def test_template_import_with_alias(tmp_path: Path) -> None:
    """!from ... import Name as Alias：别名可用，原名不可见。"""
    tpl = tmp_path / 'templates' / 'extra.inft'
    _write(tpl, '~Extra {\n    name: str = "x"\n}\n')
    f = tmp_path / 'app.infd'
    _write(
        f,
        '!from "templates/extra.inft" import Extra as Ex\na = Ex(name="y")\n',
    )
    result = load(f, sandbox=SandboxConfig(allow_templates=['./templates/*.inft']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'a': {'name': 'y'}}

    # 原名不可见（按需导入语义）
    f2 = tmp_path / 'app2.infd'
    _write(f2, '!from "templates/extra.inft" import Extra as Ex\nb = Extra(name="z")\n')
    result2 = load(f2, sandbox=SandboxConfig(allow_templates=['./templates/*.inft']))
    assert result2.has_errors
    assert any(d.code == 'template.undefined' for d in result2.diagnostics)


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
    assert any(d.code == 'template.import_conflict_local' for d in result.diagnostics)


def test_template_import_alias_missing_source(tmp_path: Path) -> None:
    tpl = tmp_path / 'extra.inft'
    _write(tpl, '~Extra {\n    name: str = "x"\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '!from "extra.inft" import DoesNotExist as X\n')
    result = load(f, sandbox=SandboxConfig.development())
    assert result.has_errors
    assert any(d.code == 'template.import_not_found' for d in result.diagnostics)


def test_template_import_nested(tmp_path: Path) -> None:
    """嵌套导入：mid 引用 base 的模板（定义点可见）；主文件只见 Mid。"""
    base = tmp_path / 'templates' / 'base.inft'
    _write(base, '~Base {\n    id: int = 0\n}\n')
    mid = tmp_path / 'templates' / 'mid.inft'
    _write(mid, '!from "base.inft" import Base\n~Mid {\n    base: Base = Base()\n}\n')
    f = tmp_path / 'app.infd'
    # Base 对主文件不可见，参数值按调用点可见性解析 → 用 dict 字面量（模板即约束校验）
    _write(f, '!from "templates/mid.inft" import Mid\nm = Mid(base={ id = 7 })\n')
    result = load(f, sandbox=SandboxConfig.development())
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'m': {'base': {'id': 7}}}


def test_template_import_unauthorized_denied(tmp_path: Path) -> None:
    tpl = tmp_path / 'templates' / 'extra.inft'
    _write(tpl, '~Extra {\n    name: str = "x"\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '!from "templates/extra.inft" import Extra\nval = Extra()\n')
    result = load(f, sandbox=SandboxConfig(allow_templates=['./allowed/*.inft']))
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['sandbox.access_denied']
    assert result.value == {}


def test_template_import_conflict_with_local(tmp_path: Path) -> None:
    tpl = tmp_path / 'extra.inft'
    _write(tpl, '~Server {\n    host: str = "0.0.0.0"\n}\n')
    f = tmp_path / 'app.infd'
    _write(f, '~Server {\n    port: int = 80\n}\n!from "extra.inft" import Server\n')
    result = load(f, sandbox=SandboxConfig.development())
    assert result.has_errors
    assert any(d.code == 'template.import_conflict_local' for d in result.diagnostics)


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


def test_same_content_different_files_is_rejected(tmp_path: Path) -> None:
    """内容 hash 真名相同但来源文件不同 → 显式报错（依赖上下文可能不同）。"""
    shared = '~Shared {\n    id: int = 0\n}\n'
    _write(tmp_path / 'a' / 'shared.inft', shared)
    _write(tmp_path / 'b' / 'shared.inft', shared)
    f = tmp_path / 'app.infd'
    _write(
        f,
        '!from "a/shared.inft" import Shared as A\n!from "b/shared.inft" import Shared as B\n',
    )
    result = load(f, sandbox=SandboxConfig.development())
    assert result.has_errors
    assert any(d.code == 'template.same_content_diff_file' for d in result.diagnostics)


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
    result = load(f, schema=Schema(template='AppConfig'))
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['schema.failed']
    assert result.value == {}


def test_schema_strict_extra_field_fails(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, '~AppConfig {\n    name: str = "x"\n}\nname = "x"\nextra = 1\n')
    result = load(f, schema=Schema(template='AppConfig', mode='strict'))
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['schema.failed']
    assert result.value == {}


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
    result = load(f, schema=Schema(template='AppConfig'))
    assert result.has_errors
    assert [d.code for d in result.diagnostics] == ['schema.failed']
    assert result.value == {}


# ═══════════════════════════════════════════════════════
# 自举：SandboxConfig(**safe_load) + compile_document
# ═══════════════════════════════════════════════════════


def test_sandbox_config_bootstrap(tmp_path: Path) -> None:
    sandbox_def = tmp_path / 'sandbox.infd'
    _write(
        sandbox_def,
        'env = { USER = "alice" }\nallow_files ["./configs/*.json"]\nstrict = true\n',
    )
    sb = SandboxConfig(**safe_load(sandbox_def).value)
    assert sb.env == {'USER': 'alice'}
    assert sb.allow_files == ['./configs/*.json']
    assert sb.strict is True


def test_compile_document(tmp_path: Path) -> None:
    f = tmp_path / 'app.infd'
    _write(f, 'name = "demo"\n')
    doc = compile_document(f)
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
