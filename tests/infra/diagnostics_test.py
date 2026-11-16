"""infra/diagnostics.py 单元测试：声明 / 注册 / 渲染 / 收集器 / 语言探测。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Mapping

import pytest

from infinity_data.infra.diagnostics import (
    DEFAULT_LANG,
    I18N_FALLBACK_MARKER,
    Diagnostic,
    DiagnosticCollector,
    DiagnosticDeclaration,
    DiagnosticRegistry,
    Severity,
    detect_lang,
)
from infinity_data.infra.file import MemFile
from infinity_data.infra.location import SourceInfo, SourceRange


@dataclass(frozen=True)
class _Hello(DiagnosticDeclaration):
    """测试用双语声明。"""

    code: ClassVar[str] = 'test.hello'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '你好 {name}',
        'en-US': 'hello {name}',
    }
    name: str


@dataclass(frozen=True)
class _Located(DiagnosticDeclaration):
    """测试用位置/路径前缀声明。"""

    code: ClassVar[str] = 'test.located'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}{path_prefix}出错了',
        'en-US': '{location_prefix}{path_prefix}boom',
    }


@dataclass(frozen=True)
class _EnglishOnly(DiagnosticDeclaration):
    """测试用仅英文声明（回退可见性）。"""

    code: ClassVar[str] = 'test.english_only'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {'en-US': 'english only {v}'}
    v: int


def test_severity_values() -> None:
    assert Severity.ERROR.value == 'error'
    assert Severity.WARNING.value == 'warning'
    assert Severity.INFO.value == 'info'


def test_render_bilingual() -> None:
    d = Diagnostic(_Hello(name='世界'), lang='zh-CN')
    assert d.render() == '你好 世界'
    assert d.render(lang='en-US') == 'hello 世界'


def test_render_fallback_is_visible() -> None:
    d = Diagnostic(_EnglishOnly(v=1), lang='fr-FR')
    expected = I18N_FALLBACK_MARKER.format(lang='en-US', message='english only 1')
    assert d.render() == expected
    assert d.render(lang='en-US') == 'english only 1'


def test_render_unsupported_language_prefers_english() -> None:
    """请求语言不支持时优先回退默认语言 en-US，而不是中文。"""
    d = Diagnostic(_Hello(name='x'), lang='de-DE')
    assert d.render() == I18N_FALLBACK_MARKER.format(lang='en-US', message='hello x')


def test_render_location_and_path_prefix() -> None:
    f = MemFile(name='f.infd', root_path=Path('.'), content='')
    d = Diagnostic(
        _Located(),
        SourceRange.at(f, SourceInfo(line=1, col=2, index=1)),
        path='a.b',
        lang='en-US',
    )
    assert d.location == 'f.infd:1:2'
    assert d.render() == '[f.infd:1:2] a.b: boom'
    assert d.render(include_location=False) == 'a.b: boom'


def test_to_dict_structure() -> None:
    f = MemFile(name='f.infd', root_path=Path('.'), content='')
    d = Diagnostic(_Hello(name='x'), SourceRange.at(f, SourceInfo(line=1, col=2, index=1)), lang='zh-CN')
    data = d.to_dict()
    assert data['code'] == 'test.hello'
    assert data['severity'] == 'error'
    assert data['lang'] == 'zh-CN'
    assert data['fallback'] is False
    assert data['params'] == {'name': 'x'}
    assert data['location'] == 'f.infd:1:2'
    assert data['message'] == '你好 x'


def test_collector_add_and_severity_queries() -> None:
    col = DiagnosticCollector(lang='zh-CN')
    assert not col.has_errors
    assert not col.has_warnings
    assert list(col) == []
    col.add(_Hello(name='a'))
    col.add(_EnglishOnly(v=2))
    assert col.has_errors
    assert col.has_warnings
    assert [d.code for d in col] == ['test.hello', 'test.english_only']
    assert [d.code for d in col.diagnostics] == ['test.hello', 'test.english_only']
    assert [d.code for d in col.errors] == ['test.hello']
    assert [d.code for d in col.warnings] == ['test.english_only']
    assert [d.lang for d in col] == ['zh-CN', 'zh-CN']


def test_collector_warning_only_is_not_errors() -> None:
    col = DiagnosticCollector(lang='zh-CN')
    col.add(_EnglishOnly(v=2))
    assert not col.has_errors
    assert col.has_warnings
    assert list(col.errors) == []
    assert [d.code for d in col.warnings] == ['test.english_only']


def test_collector_severity_override() -> None:
    col = DiagnosticCollector(lang='en-US')
    col.add(_Hello(name='soft'), severity=Severity.WARNING)
    assert not col.has_errors
    assert [d.code for d in col.warnings] == ['test.hello']
    assert col.diagnostics[0].severity is Severity.WARNING


def test_collector_extend_fills_lang() -> None:
    col = DiagnosticCollector(lang='zh-CN')
    col.extend([Diagnostic(_Hello(name='x'))])
    assert col.diagnostics[0].lang == 'zh-CN'


def test_sort_key_orders_by_location() -> None:
    f = MemFile(name='f.infd', root_path=Path('.'), content='')
    d1 = Diagnostic(_Hello(name='a'), SourceRange.at(f, SourceInfo(line=2, col=1, index=3)))
    d2 = Diagnostic(_Hello(name='b'), SourceRange.at(f, SourceInfo(line=1, col=1, index=0)))
    assert sorted([d1, d2], key=lambda d: d.sort_key())[0].source is d2.source


def test_registry_register_and_languages() -> None:
    reg = DiagnosticRegistry()
    assert reg.register(_Hello) is _Hello
    assert reg.get('test.hello') is _Hello
    assert reg.codes() == ('test.hello',)
    assert reg.available_languages() == ('zh-CN', 'en-US')


def test_global_registry_is_complete() -> None:
    """全部内置声明已导入并注册：完整性校验通过、双语言覆盖。"""
    from infinity_data.infra.diagnostics import registry

    registry.validate()
    assert {'zh-CN', 'en-US'} <= set(registry.available_languages())
    assert len(registry.codes()) >= 150


def test_registry_duplicate_code_rejected() -> None:
    reg = DiagnosticRegistry()
    reg.register(_Hello)

    @dataclass(frozen=True)
    class Other(DiagnosticDeclaration):
        code: ClassVar[str] = 'test.hello'
        severity: ClassVar[Severity] = Severity.ERROR
        templates: ClassVar[Mapping[str, str]] = {'en-US': 'other'}

    with pytest.raises(ValueError, match='duplicate diagnostic code'):
        reg.register(Other)


def test_registry_rejects_missing_english() -> None:
    reg = DiagnosticRegistry()

    @dataclass(frozen=True)
    class NoEnglish(DiagnosticDeclaration):
        code: ClassVar[str] = 'test.no_english'
        severity: ClassVar[Severity] = Severity.ERROR
        templates: ClassVar[Mapping[str, str]] = {'zh-CN': '只有中文'}

    with pytest.raises(ValueError, match='en-US template is required'):
        reg.register(NoEnglish)


def test_registry_rejects_unknown_placeholder() -> None:
    reg = DiagnosticRegistry()

    @dataclass(frozen=True)
    class BadPlaceholder(DiagnosticDeclaration):
        code: ClassVar[str] = 'test.bad_placeholder'
        severity: ClassVar[Severity] = Severity.ERROR
        templates: ClassVar[Mapping[str, str]] = {'en-US': '{missing}'}

    with pytest.raises(ValueError, match='unknown placeholders'):
        reg.register(BadPlaceholder)


def test_registry_rejects_reserved_parameter() -> None:
    reg = DiagnosticRegistry()

    @dataclass(frozen=True)
    class Reserved(DiagnosticDeclaration):
        code: ClassVar[str] = 'test.reserved'
        severity: ClassVar[Severity] = Severity.ERROR
        templates: ClassVar[Mapping[str, str]] = {'en-US': '{path_prefix}x'}
        path_prefix: str

    with pytest.raises(ValueError, match='reserved parameter'):
        reg.register(Reserved)


def test_registry_rejects_any_parameter() -> None:
    reg = DiagnosticRegistry()

    @dataclass(frozen=True)
    class AnyParam(DiagnosticDeclaration):
        code: ClassVar[str] = 'test.any_param'
        severity: ClassVar[Severity] = Severity.ERROR
        templates: ClassVar[Mapping[str, str]] = {'en-US': '{value}'}
        value: Any

    with pytest.raises(ValueError, match='Any/object'):
        reg.register(AnyParam)


def test_registry_rejects_non_dataclass() -> None:
    reg = DiagnosticRegistry()

    class NotDataclass(DiagnosticDeclaration):
        code: ClassVar[str] = 'test.not_dataclass'
        severity: ClassVar[Severity] = Severity.ERROR
        templates: ClassVar[Mapping[str, str]] = {'en-US': 'x'}

    with pytest.raises(TypeError, match='must be a dataclass'):
        reg.register(NotDataclass)


def test_render_unknown_template_is_fixed_error_text() -> None:
    @dataclass(frozen=True)
    class NoTemplates(DiagnosticDeclaration):
        code: ClassVar[str] = 'test.no_templates'
        severity: ClassVar[Severity] = Severity.ERROR
        templates: ClassVar[Mapping[str, str]] = {}

    d = Diagnostic(NoTemplates(), lang='en-US')
    assert d.render() == '[diagnostic render failed: test.no_templates]'


def test_detect_lang_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE'):
        monkeypatch.delenv(name, raising=False)
    assert detect_lang() == DEFAULT_LANG

    monkeypatch.setenv('LANG', 'de_DE.UTF-8')
    assert detect_lang() == DEFAULT_LANG  # 非中英文 locale 不再落到中文

    monkeypatch.setenv('LANG', 'zh_CN.UTF-8')
    assert detect_lang() == 'zh-CN'

    monkeypatch.setenv('LC_MESSAGES', 'fr_FR.UTF-8')
    assert detect_lang() == DEFAULT_LANG  # 不支持的语言直接回落默认语言

    monkeypatch.delenv('LC_MESSAGES')
    monkeypatch.setenv('LANG', 'zh')
    assert detect_lang() == DEFAULT_LANG

    monkeypatch.setenv('LANGUAGE', 'fr_FR:zh_CN.UTF-8')
    assert detect_lang() == 'zh-CN'  # 优先选择已支持的语言


def test_language_overrides_posix_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    """GNU LANGUAGE 优先于 LC_ALL / LC_MESSAGES / LANG。"""
    for name in ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE'):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv('LC_ALL', 'zh_CN.UTF-8')
    monkeypatch.setenv('LANGUAGE', 'en_US:zh_CN')
    assert detect_lang() == 'en-US'

    monkeypatch.setenv('LC_ALL', 'de_DE.UTF-8')
    monkeypatch.setenv('LANGUAGE', 'fr_FR:en_US')
    assert detect_lang() == 'en-US'


def test_c_locale_disables_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """C / POSIX locale 禁用翻译，即使 LANGUAGE 请求中文也回落英文。"""
    for name in ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE'):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv('LC_ALL', 'C')
    monkeypatch.setenv('LANGUAGE', 'zh_CN')
    assert detect_lang() == DEFAULT_LANG

    monkeypatch.setenv('LC_ALL', 'POSIX.UTF-8')
    assert detect_lang() == DEFAULT_LANG


def test_posix_locale_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 LANGUAGE 时按 LC_ALL > LC_MESSAGES > LANG 选择语言。"""
    for name in ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE'):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv('LC_ALL', 'zh_CN.UTF-8')
    monkeypatch.setenv('LC_MESSAGES', 'de_DE.UTF-8')
    monkeypatch.setenv('LANG', 'en_US.UTF-8')
    assert detect_lang() == 'zh-CN'
