"""path 原生类型测试：p"..." 字面量、导入强制路径、path 约束族（含沙盒授权）。

覆盖三层：
- 词法：``p"..."`` → PATH token / :class:`PathToken`（:class:`PosixPath` 承载）
- 语法：``!file`` / ``!from`` 路径必须用 ``p"..."``（普通字符串 → ``parse.import_path_required``）
- 语义：``path`` 纯语法约束 + ``exist`` / ``dir`` / ``file`` / ``link`` 文件系统约束
  （经沙盒 allow_files 授权；越出沙盒 → ``constraint.path_denied`` 警告 + 失败）
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PosixPath

from infinity_data import SandboxConfig, Severity, compile_source, load
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.models.raw_tokens import RawTokenType
from infinity_data.tokenizer.models.tokens import PathToken
from infinity_data.tokenizer.tokenizer import RawTokenizer


def _tokenize(src: str):
    col = DiagnosticCollector()
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    return list(RawTokenizer(file=file, error_collector=col)), col


def _final(src: str):
    toks, col = _tokenize(src)
    return list(FinalTokenizer(toks, error_collector=col)), col


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding='utf-8')
    return p


# ═══════════════════════════════════════════════════════════
# 词法：p"..." 路径字面量
# ═══════════════════════════════════════════════════════════


def test_path_literal_raw_token() -> None:
    toks, col = _tokenize('p"/etc/certs/a.pem"')
    assert not col.has_errors
    assert toks[0].type is RawTokenType.PATH
    assert toks[0].raw == 'p"/etc/certs/a.pem"'


def test_path_literal_value_is_posix_path() -> None:
    fin, col = _final('p"/etc/certs/a.pem"')
    assert not col.has_errors
    tok = fin[0]
    assert isinstance(tok, PathToken)
    assert tok.value == PosixPath('/etc/certs/a.pem')


def test_path_literal_escapes() -> None:
    fin, col = _final(r'p"a\/b"')
    assert not col.has_errors
    assert isinstance(fin[0], PathToken) and fin[0].value == PosixPath('a/b')


def test_plain_p_identifier_when_not_followed_by_quote() -> None:
    """p 后非 " → 普通标识符（p 是合法字段名）。"""
    toks, col = _tokenize('p = 1\n')
    assert not col.has_errors
    assert [t.type for t in toks] == [
        RawTokenType.IDENTIFIER,
        RawTokenType.EQUALS,
        RawTokenType.INTEGER,
        RawTokenType.NEWLINE,
        RawTokenType.EOF,
    ]


def test_path_literal_canonical_roundtrip() -> None:
    fin, _ = _final('p"/etc/x"')
    assert isinstance(fin[0], PathToken) and fin[0].canonical() == 'p"/etc/x"'


def test_empty_path_literal_is_lex_error() -> None:
    fin, col = _final('p""')
    assert any(d.code == 'tokenize.invalid_path' for d in col)
    assert isinstance(fin[0], PathToken)


def test_unterminated_path_literal_reports() -> None:
    _, col = _tokenize('p"/abc')
    assert any(d.code == 'tokenize.unterminated_string' for d in col)


# ═══════════════════════════════════════════════════════════
# 语法：导入路径必须用 p"..."
# ═══════════════════════════════════════════════════════════


def test_file_import_accepts_path_literal(infd_file: Callable[[str, str], Path]) -> None:
    infd_file('data.json', '{"k": 1}')
    path = infd_file('app.infd', '!file p"data.json" import .k as k\nv = $k\n')
    result = load(path, sandbox=SandboxConfig(allow_files=['./data.json']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'v': 1}


def test_file_import_plain_string_is_error_recovered(infd_file: Callable[[str, str], Path]) -> None:
    """普通字符串路径 → parse.import_path_required 错误，仍容错取用继续编译。"""
    infd_file('data.json', '{"k": 1}')
    path = infd_file('app.infd', '!file "data.json" import .k as k\nv = $k\n')
    result = load(path, sandbox=SandboxConfig(allow_files=['./data.json']))
    assert any(d.code == 'parse.import_path_required' for d in result.diagnostics)
    assert result.value == {'v': 1}


def test_from_import_accepts_path_literal(infd_file: Callable[[str, str], Path]) -> None:
    infd_file('tpl.inft', '~T {\n    x: int = 1\n}\n')
    path = infd_file('app.infd', '!from p"tpl.inft" import T\nt = T()\n')
    result = load(path, sandbox=SandboxConfig(allow_templates=['./tpl.inft']))
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'t': {'x': 1}}


def test_from_import_plain_string_is_error_recovered(infd_file: Callable[[str, str], Path]) -> None:
    infd_file('tpl.inft', '~T {\n    x: int = 1\n}\n')
    path = infd_file('app.infd', '!from "tpl.inft" import T\nt = T()\n')
    result = load(path, sandbox=SandboxConfig(allow_templates=['./tpl.inft']))
    assert any(d.code == 'parse.import_path_required' for d in result.diagnostics)
    assert result.value == {'t': {'x': 1}}


# ═══════════════════════════════════════════════════════════
# 语义：path 作为值 / 约束
# ═══════════════════════════════════════════════════════════


def test_path_literal_value_keeps_posix_path() -> None:
    """.value 是忠实 std→python：path 值保持 PosixPath（有损投影在 emit 层）。"""
    result = compile_source('cert = p"/etc/certs/a.pem"\n')
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'cert': PosixPath('/etc/certs/a.pem')}


def test_path_constraint_accepts_path_literal() -> None:
    result = compile_source('cert: path = p"/etc/certs/a.pem"\n')
    assert not result.has_errors, [d.message for d in result.diagnostics]


def test_path_constraint_rejects_str() -> None:
    """str 与 path 是独立类型：字符串不满足 path（须经 as path 显式转换）。"""
    result = compile_source('cert: path = "/etc/certs/a.pem"\n')
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)


def test_path_constraint_rejects_non_path() -> None:
    result = compile_source('x: path = 123\n')
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)


def test_path_nullable_sugar() -> None:
    result = compile_source('a: <path?> = null\nb: <path?> = p"/x"\n')
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'a': None, 'b': PosixPath('/x')}


def test_path_each_in_list() -> None:
    """each(path)：元素须为 path 类型；str 元素被拒绝。"""
    ok = compile_source('paths: <list, each(path)> = [p"/a", p"/b"]\n')
    assert not ok.has_errors, [d.message for d in ok.diagnostics]
    assert ok.value == {'paths': [PosixPath('/a'), PosixPath('/b')]}
    bad = compile_source('bad: <list, each(path)> = [p"/a", "/b"]\n')
    assert any(d.code == 'constraint.type_mismatch' for d in bad.diagnostics)


def test_str_constraint_rejects_path_value() -> None:
    """str 与 path 独立：str 约束拒绝 path 值。"""
    result = compile_source('x: str = p"/a"\n')
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)


def test_size_constraint_rejects_path_value() -> None:
    """size 是字符串/集合约束：path 是独立类型，不适用。"""
    result = compile_source('x: <path, size(2)> = p"/ab"\n')
    assert any(d.code == 'constraint.size_only' for d in result.diagnostics)


def test_eq_path_no_cross_kind() -> None:
    """eq(p"/x") 只对 path 值成立；等价 str 值不相等（path 与 str 独立）。"""
    a = compile_source('a: <eq(p"/x")> = p"/x"\n')
    assert not a.has_errors, [d.message for d in a.diagnostics]
    b = compile_source('b: <eq(p"/x")> = "/x"\n')
    assert any(d.code == 'constraint.eq_mismatch' for d in b.diagnostics)
    c = compile_source('c: <eq(p"/x")> = "/y"\n')
    assert any(d.code == 'constraint.eq_mismatch' for d in c.diagnostics)


def test_in_choices_with_paths() -> None:
    """in(p"/a", p"/b") 只匹配 path 值；str 不参与（无交叉相等）。"""
    ok = compile_source('x: <in(p"/a", p"/b")> = p"/a"\n')
    assert not ok.has_errors, [d.message for d in ok.diagnostics]
    bad = compile_source('y: <in(p"/a", p"/b")> = "/a"\n')
    assert any(d.code == 'constraint.in_not_in' for d in bad.diagnostics)


def test_same_target_constraint() -> None:
    """same_target：词法折叠 ./.. 后同 target（纯语法、可复现）。"""
    ok = compile_source('a: <path, same_target(p"/etc/x")> = p"/etc/../etc/x"\n')
    assert not ok.has_errors, [d.message for d in ok.diagnostics]
    bad = compile_source('b: <path, same_target(p"/etc/x")> = p"/var/x"\n')
    assert any(d.code == 'constraint.same_target_mismatch' for d in bad.diagnostics)


def test_same_target_rejects_str() -> None:
    """same_target 是路径域约束：str 值 → type_mismatch（path 独立类型）。"""
    result = compile_source('x: <same_target(p"/a")> = "/a"\n')
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)


def test_same_name_constraint() -> None:
    """same_name(str)：路径 basename 等于指定字符串。"""
    ok = compile_source('a: <path, same_name("pipeline.py")> = p"/etc/pipeline.py"\n')
    assert not ok.has_errors, [d.message for d in ok.diagnostics]
    bad = compile_source('b: <path, same_name("pipeline.py")> = p"/etc/main.py"\n')
    assert any(d.code == 'constraint.same_name_mismatch' for d in bad.diagnostics)


def test_extension_constraint() -> None:
    """extension(ext, ...)：路径扩展名匹配任一（不带前导点）。"""
    ok = compile_source('a: <path, extension("json")> = p"/etc/config.json"\n')
    assert not ok.has_errors, [d.message for d in ok.diagnostics]
    multi = compile_source('b: <path, extension("json", "yaml")> = p"/etc/config.yaml"\n')
    assert not multi.has_errors, [d.message for d in multi.diagnostics]
    bad = compile_source('c: <path, extension("json")> = p"/etc/config.toml"\n')
    assert any(d.code == 'constraint.extension_mismatch' for d in bad.diagnostics)
    noext = compile_source('d: <path, extension("json")> = p"/etc/readme"\n')
    assert any(d.code == 'constraint.extension_mismatch' for d in noext.diagnostics)


def test_regex_on_path() -> None:
    """regex 推广到 path：对 POSIX 字符串全匹配（fullmatch，[.] 避免转义）。"""
    ok = compile_source('a: <path, regex(".*[.]pem")> = p"/etc/certs/a.pem"\n')
    assert not ok.has_errors, [d.message for d in ok.diagnostics]
    bad = compile_source('b: <path, regex(".*[.]pem")> = p"/etc/certs/a.key"\n')
    assert any(d.code == 'constraint.regex_no_match' for d in bad.diagnostics)


def test_path_in_template_default_and_field() -> None:
    result = compile_source(
        """
~Cfg {
    out: path
    cert: <path> = p"/etc/default.pem"
}
c = Cfg(out = p"/tmp/x")
"""
    )
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'c': {'cert': PosixPath('/etc/default.pem'), 'out': PosixPath('/tmp/x')}}


def test_dollar_as_path_cast() -> None:
    """$name as path：字符串 → path 值（供 path 约束消费）。"""
    result = compile_source(
        """
!var "/etc/certs/a.pem" import . as raw
cert: path = $raw as path
"""
    )
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'cert': PosixPath('/etc/certs/a.pem')}


def test_path_value_in_dict_and_var() -> None:
    result = compile_source(
        """
!var p"/var/lib" import . as lib
cfg = { root = $lib, extra = p"/tmp" }
"""
    )
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'cfg': {'root': PosixPath('/var/lib'), 'extra': PosixPath('/tmp')}}


def test_path_value_as_str_cast() -> None:
    """as str 对 path 值 → POSIX 字符串。"""
    result = compile_source(
        """
!var p"/c/foo" import . as p
s: str = $p as str
"""
    )
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'s': '/c/foo'}


# ═══════════════════════════════════════════════════════════
# 文件系统约束（exist / dir / file / link，沙盒授权）
# ═══════════════════════════════════════════════════════════


def test_exist_constraint_pass(tmp_path: Path, infd_file: Callable[[str, str], Path]) -> None:
    _write(tmp_path / 'data.json', '{}')
    path = infd_file('app.infd', 'f: <path, exist> = p"./data.json"\n')
    result = load(path, sandbox=SandboxConfig(allow_files=['./data.json']))
    assert not result.has_errors, [d.message for d in result.diagnostics]


def test_exist_constraint_missing_fails(tmp_path: Path, infd_file: Callable[[str, str], Path]) -> None:
    path = infd_file('app.infd', 'f: <path, exist> = p"./nope.json"\n')
    result = load(path, sandbox=SandboxConfig(allow_files=['./**']))
    assert any(d.code == 'constraint.path_not_exist' for d in result.diagnostics)


def test_dir_and_file_constraints(tmp_path: Path, infd_file: Callable[[str, str], Path]) -> None:
    _write(tmp_path / 'data.json', '{}')
    (tmp_path / 'sub').mkdir()
    ok = infd_file('ok.infd', 'd: <path, dir> = p"./sub"\nf: <path, file> = p"./data.json"\n')
    r = load(ok, sandbox=SandboxConfig(allow_files=['./**']))
    assert not r.has_errors, [d.message for d in r.diagnostics]

    bad = infd_file('bad.infd', 'd: <path, dir> = p"./data.json"\n')
    r2 = load(bad, sandbox=SandboxConfig(allow_files=['./**']))
    assert any(d.code == 'constraint.path_not_dir' for d in r2.diagnostics)


def test_fs_constraint_denied_is_warning_and_fail(tmp_path: Path, infd_file: Callable[[str, str], Path]) -> None:
    """越出沙盒（allow_files 白名单外）→ constraint.path_denied：警告 + 失败。

    - 约束不满足（ok=False）：后续约束链短路
    - 诊断级别为 WARNING（非硬错误，has_errors=False）
    """
    _write(tmp_path / 'secret.json', '{}')
    path = infd_file('app.infd', 'f: <path, exist> = p"./secret.json"\n')
    result = load(path, sandbox=SandboxConfig.deny_all())
    denied = [d for d in result.diagnostics if d.code == 'constraint.path_denied']
    assert denied, [d.message for d in result.diagnostics]
    assert denied[0].severity is Severity.WARNING
    assert not result.has_errors  # 警告不构成编译错误


def test_fs_constraint_rejects_str_value(tmp_path: Path, infd_file: Callable[[str, str], Path]) -> None:
    """文件系统约束只接受 path 类型：str 值 → type_mismatch（导入字符串须 as path）。"""
    _write(tmp_path / 'data.json', '{"p": "/etc/x"}')
    path = infd_file('app.infd', '!file p"data.json" import .p as p\nf: <path, exist> = $p\n')
    result = load(path, sandbox=SandboxConfig(allow_files=['./data.json']))
    # $p 是 str（JSON 字符串），path/exist 均拒绝 → type_mismatch
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)


def test_fs_constraint_type_mismatch(tmp_path: Path, infd_file: Callable[[str, str], Path]) -> None:
    path = infd_file('app.infd', 'x: <exist> = 42\n')
    result = load(path, sandbox=SandboxConfig.full_access())
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)
