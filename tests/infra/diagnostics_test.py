"""infra/diagnostics.py 单元测试：Diagnostic / 注册表 / 渲染 / 收集器。"""

from pathlib import Path

from infinity_data.infra.diagnostics import (
    Diagnostic,
    DiagnosticCollector,
    Severity,
    diagnostic_define,
    register_diagnostic_define,
    render_message,
)
from infinity_data.infra.file import MemFile
from infinity_data.infra.location import SourceInfo, SourceRange


def test_severity_values() -> None:
    assert Severity.ERROR.value == 'error'
    assert Severity.WARNING.value == 'warning'
    assert Severity.INFO.value == 'info'


def test_render_unknown_code_returns_code() -> None:
    assert render_message('no.such.code', {}) == 'no.such.code'


def test_register_and_render_with_translation() -> None:
    register_diagnostic_define(diagnostic_define('test.hello', '你好 {name}', en='hello {name}'))
    assert render_message('test.hello', {'name': '世界'}) == '你好 世界'
    assert render_message('test.hello', {'name': 'world'}, lang='en') == 'hello world'


def test_render_fallback_to_default_lang() -> None:
    register_diagnostic_define(diagnostic_define('test.noen', '只有中文 {v}'))
    assert render_message('test.noen', {'v': 1}, lang='en') == '只有中文 1'


def test_diagnostic_location_and_message() -> None:
    register_diagnostic_define(diagnostic_define('test.loc', '[{location}] 出错 {v}'))
    f = MemFile(name='f.infd', root_path=Path('.'), content='')
    d = Diagnostic(
        Severity.ERROR,
        'test.loc',
        {'v': 7},
        SourceRange.at(f, SourceInfo(line=1, col=2, index=1)),
    )
    assert d.location == 'f.infd:1:2'
    assert '出错 7' in d.message


def test_collector_iteration_and_has_errors() -> None:
    col = DiagnosticCollector()
    assert not col.has_errors
    assert list(col) == []
    col.add(Diagnostic(Severity.ERROR, 'a.b', {}))
    col.add(Diagnostic(Severity.WARNING, 'c.d', {}))
    assert col.has_errors
    assert [d.code for d in col] == ['a.b', 'c.d']
    assert col.errors == [d for d in col]  # errors 返回副本


def test_sort_key_orders_by_location() -> None:
    f = MemFile(name='f.infd', root_path=Path('.'), content='')
    d1 = Diagnostic(Severity.ERROR, 'a', {}, SourceRange.at(f, SourceInfo(line=2, col=1, index=3)))
    d2 = Diagnostic(Severity.ERROR, 'b', {}, SourceRange.at(f, SourceInfo(line=1, col=1, index=0)))
    assert sorted([d1, d2], key=lambda d: d.sort_key())[0].code == 'b'
