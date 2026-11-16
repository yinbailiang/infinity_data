"""统一诊断模型（所有阶段共用）与容错收集器。

核心约定（详见 `ENGINEERING.md` 的「诊断模型」章节）：

- **单层定义**：诊断声明类本身即参数 dataclass
  （``code`` / ``severity`` / ``templates`` 为 ``ClassVar``，字段为渲染参数）
- **声明式注册**：``@registry.register`` 装饰器完成注册 + 注册期校验
- **类型化参数**：字段按真实类型标注，禁止 ``Any`` / ``object`` 兜底
- **多语言**：精确语言标签 ``zh-CN`` / ``en-US``；请求缺失时按固定回退链
  （请求语言 → ``I18N_LANGS_FALLBACK``），回退可见性写入消息正文
- **收集器**：词法/语法/语义阶段容错收集，从不抛异常

用法::

    @registry.register
    @dataclass(frozen=True)
    class DictDuplicateKey(DiagnosticDeclaration):
        code: ClassVar[str] = 'dict.duplicate_key'
        severity: ClassVar[Severity] = Severity.ERROR
        templates: ClassVar[Mapping[str, str]] = {
            'zh-CN': '{path_prefix}键 {name!r} 重复定义',
            'en-US': '{path_prefix}duplicate key {name!r}',
        }
        name: str

    collector.add(DictDuplicateKey(name='a'), source, path='a')
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from decimal import Decimal
from enum import Enum
from pathlib import PurePath
from string import Formatter
from types import MappingProxyType, UnionType
from typing import Any, ClassVar, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from infinity_data.infra.location import SourceRange, format_location

__all__ = [
    'DEFAULT_LANG',
    'I18N_FALLBACK_MARKER',
    'I18N_LANGS_FALLBACK',
    'I18N_RENDER_ERROR',
    'SUPPORTED_LANGS',
    'Severity',
    'DiagnosticDeclaration',
    'DiagnosticRegistry',
    'registry',
    'Diagnostic',
    'DiagnosticCollector',
    'detect_lang',
    'register',
]

DEFAULT_LANG = 'en-US'
"""默认渲染语言（探测失败回落英文）。"""

SUPPORTED_LANGS: tuple[str, ...] = ('zh-CN', 'en-US')
"""支持的语言标签（精确匹配，不做语言码归一化）。"""

I18N_LANGS_FALLBACK: tuple[str, ...] = ('en-US', 'zh-CN')
"""固定回退链（请求语言之后依次尝试；优先默认语言 en-US）。"""

I18N_FALLBACK_MARKER = '[fallback: {lang}] {message}'
"""回退可见性标记（出现在用户消息正文中，工具不得解析消息文本）。"""

I18N_RENDER_ERROR = '[diagnostic render failed: {code}]'
"""渲染异常兜底文案（占位符问题等，绝不返回空串或崩溃）。"""

_LOCALE_ENV_VARS: tuple[str, ...] = ('LC_ALL', 'LC_MESSAGES', 'LANG')
"""POSIX locale 环境变量优先级（GNU ``LANGUAGE`` 扩展单独处理）。"""

_LANGUAGE_ENV = 'LANGUAGE'
"""GNU gettext 消息语言偏好列表（优先级高于 POSIX locale）。"""

_RESERVED_CONTEXT_NAMES = frozenset({'location_prefix', 'path_prefix'})
"""渲染器保留的上下文占位符（声明字段不得同名）。"""

_CLASS_VAR_NAMES = frozenset({'code', 'severity', 'templates'})

_TDeclaration = TypeVar('_TDeclaration', bound=type['DiagnosticDeclaration'])
"""注册装饰器的类型变量（保留子类构造签名）。"""


class Severity(Enum):
    """诊断严重级别。"""

    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'
    DEBUG = 'debug'


def _parse_locale(raw: str) -> str | None:
    """把 POSIX 语言环境解析为 ``ll-CC``（仅边界归一化，不做语言码宽松匹配）。

    - ``zh_CN.UTF-8`` → ``zh-CN``
    - ``zh`` / ``C`` / ``POSIX``（无国家码）→ ``None``
    - 冒号分隔列表（GNU ``LANGUAGE``）返回首个已支持语言，否则返回首个可解析项
    """
    first: str | None = None
    for part in raw.split(':'):
        value = part.strip()
        if not value:
            continue
        base = value.split('.', 1)[0].split('@', 1)[0]
        if '_' not in base:
            continue
        lang, country = base.split('_', 1)
        if not lang or not country:
            continue
        parsed = f'{lang.lower()}-{country.upper()}'
        if first is None:
            first = parsed
        if parsed in SUPPORTED_LANGS:
            return parsed
    return first


def _is_c_locale(raw: str) -> bool:
    """是否为禁用翻译的 C / POSIX locale。"""
    value = raw.split(':', 1)[0].split('.', 1)[0].split('@', 1)[0].strip().lower()
    return value in ('c', 'posix')


def _parse_language_list(raw: str) -> str | None:
    """GNU ``LANGUAGE`` 偏好列表 → 首个已支持语言。"""
    for part in raw.split(':'):
        parsed = _parse_locale(part)
        if parsed in SUPPORTED_LANGS:
            return parsed
    return None


def detect_lang() -> str:
    """按环境变量探测语言。

    优先级：``LANGUAGE``（GNU gettext 偏好列表）> ``LC_ALL`` > ``LC_MESSAGES`` > ``LANG``。
    ``LANGUAGE`` 中的语言都不支持时，回落到 POSIX locale；
    ``C`` / ``POSIX`` locale 禁用翻译，直接回退 :data:`DEFAULT_LANG`。
    探测到不支持的语言时同样回退 :data:`DEFAULT_LANG`，避免默认落到中文。
    """
    effective_raw = next((os.environ[name] for name in _LOCALE_ENV_VARS if os.environ.get(name)), None)
    if effective_raw is not None and _is_c_locale(effective_raw):
        return DEFAULT_LANG

    language_raw = os.environ.get(_LANGUAGE_ENV)
    if language_raw:
        preferred = _parse_language_list(language_raw)
        if preferred is not None:
            return preferred

    if effective_raw is None:
        return DEFAULT_LANG
    parsed = _parse_locale(effective_raw)
    if parsed is None:
        return DEFAULT_LANG
    return parsed if parsed in SUPPORTED_LANGS else DEFAULT_LANG


class DiagnosticDeclaration:
    """诊断声明基类：子类必须是 ``@dataclass(frozen=True)``。

    类属性（``ClassVar``）：

    - ``code``：稳定错误码（全局唯一）
    - ``severity``：默认严重级别（``Diagnostic.severity`` 可覆盖）
    - ``templates``：语言标签 → 模板（必须含 ``en-US``）

    数据字段：渲染参数，按真实类型标注（禁止 ``Any`` / ``object``）。
    """

    code: ClassVar[str]
    severity: ClassVar[Severity]
    templates: ClassVar[Mapping[str, str]]

    @classmethod
    def parameter_names(cls) -> tuple[str, ...]:
        """声明的参数字段名（非 dataclass 子类返回空元组）。"""
        if not is_dataclass(cls):
            return ()
        return tuple(f.name for f in fields(cls))

    def parameters(self) -> dict[str, Any]:
        """声明实例的参数键值（渲染上下文 / JSON 报告共用）。"""
        if not is_dataclass(self):
            return {}
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _contains_any(annotation: Any) -> bool:
    """类型标注是否含 ``Any`` / ``object``（含联合与容器参数递归检查）。"""
    if annotation in (Any, object):
        return True
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return any(_contains_any(arg) for arg in get_args(annotation))
    return any(_contains_any(arg) for arg in get_args(annotation) if arg is not type(None))


def _template_placeholders(template: str) -> set[str]:
    """提取模板中的占位符名（拒绝位置占位符 / 属性访问 / 下标访问）。"""
    names: set[str] = set()
    for _, field_name, format_spec, _ in Formatter().parse(template):
        if field_name is None:
            continue
        if not field_name.isidentifier():
            raise ValueError(f'invalid placeholder {{{field_name}}} (named parameters only)')
        names.add(field_name)
        if format_spec and '{' in format_spec:
            names.update(_template_placeholders(format_spec))
    return names


def _validate_declaration(cls: type[DiagnosticDeclaration]) -> None:
    """注册期校验：dataclass、code 唯一合法、severity、模板完整、占位符一致、字段类型。"""
    if not is_dataclass(cls):
        raise TypeError(f'{cls.__qualname__}: diagnostic declaration must be a dataclass')

    code = getattr(cls, 'code', None)
    if not isinstance(code, str) or not code:
        raise ValueError(f'{cls.__qualname__}: code must be a non-empty string')

    severity = getattr(cls, 'severity', None)
    if not isinstance(severity, Severity):
        raise ValueError(f'{cls.__qualname__}: severity must be a Severity')

    templates_obj = getattr(cls, 'templates', None)
    if not isinstance(templates_obj, Mapping):
        raise ValueError(f'{cls.__qualname__}: templates must be a mapping')
    templates = cast(Mapping[str, str], templates_obj)
    for lang, template in templates.items():
        if lang not in SUPPORTED_LANGS:
            raise ValueError(f'{cls.__qualname__}: unsupported language {lang!r}')
        if not template:
            raise ValueError(f'{cls.__qualname__}: empty template for {lang!r}')
    if 'en-US' not in templates:
        raise ValueError(f'{cls.__qualname__}: en-US template is required')

    param_names = set(cls.parameter_names())
    reserved = param_names & _RESERVED_CONTEXT_NAMES
    if reserved:
        raise ValueError(f'{cls.__qualname__}: reserved parameter name(s): {sorted(reserved)}')
    if _CLASS_VAR_NAMES & param_names:
        raise ValueError(f'{cls.__qualname__}: {sorted(_CLASS_VAR_NAMES & param_names)} must be ClassVar')

    try:
        hints = get_type_hints(cls)
    except NameError as e:  # pragma: no cover - 声明模块必须可解析
        raise ValueError(f'{cls.__qualname__}: cannot resolve parameter annotations: {e}') from e
    for field_info in fields(cls):
        annotation = hints.get(field_info.name, field_info.type)
        if _contains_any(annotation):
            raise ValueError(f'{cls.__qualname__}.{field_info.name}: Any/object is not allowed')

    allowed = param_names | _RESERVED_CONTEXT_NAMES
    for lang, template in templates.items():
        placeholders = _template_placeholders(template)
        unknown = placeholders - allowed
        if unknown:
            raise ValueError(f'{cls.__qualname__}: template {lang!r} uses unknown placeholders: {sorted(unknown)}')


class DiagnosticRegistry:
    """诊断声明注册表（全局唯一，支持语言枚举与完整性检查）。"""

    def __init__(self) -> None:
        self._declarations: dict[str, type[DiagnosticDeclaration]] = {}

    def register(self, cls: _TDeclaration) -> _TDeclaration:
        """注册声明类（装饰器形态）；重复 code 且非同一类 → 报错。"""
        _validate_declaration(cls)
        existing = self._declarations.get(cls.code)
        if existing is not None and existing is not cls:
            raise ValueError(f'duplicate diagnostic code {cls.code!r}: {existing.__qualname__} / {cls.__qualname__}')
        self._declarations[cls.code] = cls
        return cls

    def get(self, code: str) -> type[DiagnosticDeclaration] | None:
        """按错误码取声明类。"""
        return self._declarations.get(code)

    def __contains__(self, code: object) -> bool:
        return code in self._declarations

    def declarations(self) -> Mapping[str, type[DiagnosticDeclaration]]:
        """已注册声明（只读视图，code → 类）。"""
        return MappingProxyType(self._declarations)

    def codes(self) -> tuple[str, ...]:
        """全部已注册错误码（排序）。"""
        return tuple(sorted(self._declarations))

    def available_languages(self) -> tuple[str, ...]:
        """已注册模板中出现过的支持语言（按 ``SUPPORTED_LANGS`` 顺序）。"""
        langs = {lang for decl in self._declarations.values() for lang in decl.templates}
        return tuple(lang for lang in SUPPORTED_LANGS if lang in langs)

    def validate(self) -> None:
        """重新校验全部已注册声明（完整性检查入口）。"""
        for cls in self._declarations.values():
            _validate_declaration(cls)


registry = DiagnosticRegistry()
"""全局诊断声明注册表。"""


def register(declaration: _TDeclaration) -> _TDeclaration:
    """全局注册装饰器（保留子类类型信息，便于静态检查参数）。"""
    return registry.register(declaration)


def _json_value(value: Any) -> Any:
    """参数值 → JSON 友好的 Python 值（Decimal → str、Path → POSIX 字符串）。"""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list | tuple):
        items = cast(list[Any], value)
        return [_json_value(item) for item in items]
    if isinstance(value, dict):
        mapping = cast(dict[Any, Any], value)
        return {str(k): _json_value(v) for k, v in mapping.items()}
    return value


@dataclass(frozen=True)
class Diagnostic:
    """统一诊断：声明实例（同时携带类型化参数）+ 源码位置 + 渲染语言。

    - ``declaration``：诊断声明实例（``code`` / 默认 ``severity`` / 模板 / 参数）
    - ``severity_override``：覆盖声明级别（``path_denied`` 软失败、汇总降级等）；
      ``None`` = 用声明级别。``severity`` 属性始终返回实际生效级别
    - ``lang``：渲染语言（收集器构造时探测并写入）
    """

    declaration: DiagnosticDeclaration
    source: SourceRange | None = None
    path: str = ''
    severity_override: Severity | None = None
    lang: str | None = None

    @property
    def code(self) -> str:
        """稳定错误码。"""
        return self.declaration.code

    @property
    def severity(self) -> Severity:
        """实际严重级别（覆盖优先，否则声明级别）。"""
        return self.severity_override if self.severity_override is not None else self.declaration.severity

    @property
    def location(self) -> str:
        """格式化的源码位置（``file:line:col``，零宽 / 区间统一）。"""
        return format_location(self.source)

    def _select_template(self, requested: str) -> tuple[str | None, str, bool]:
        """按回退链选模板，返回 ``(模板, 实际语言, 是否回退)``。"""
        seen: set[str] = set()
        for candidate in (requested, *I18N_LANGS_FALLBACK):
            if candidate in seen:
                continue
            seen.add(candidate)
            template = self.declaration.templates.get(candidate)
            if template:
                return template, candidate, candidate != requested
        return None, requested, False

    def render(self, *, lang: str | None = None, include_location: bool = True) -> str:
        """按声明模板 + 参数渲染消息（回退可见；异常返回固定错误文案）。"""
        requested = lang or self.lang or DEFAULT_LANG
        template, used_lang, fallback = self._select_template(requested)
        if template is None:
            return I18N_RENDER_ERROR.format(code=self.code)

        context: dict[str, Any] = self.declaration.parameters()
        context['location_prefix'] = f'[{self.location}] ' if include_location else ''
        context['path_prefix'] = f'{self.path}: ' if self.path else ''
        try:
            message = template.format(**context)
        except (KeyError, IndexError, ValueError, AttributeError):
            return I18N_RENDER_ERROR.format(code=self.code)
        if not message:
            return I18N_RENDER_ERROR.format(code=self.code)
        if fallback:
            return I18N_FALLBACK_MARKER.format(lang=used_lang, message=message)
        return message

    def to_dict(self, *, lang: str | None = None, include_location: bool = False) -> dict[str, Any]:
        """结构化错误报告（CLI ``--diag-format json`` / LSP ``diagnostic.data`` 共用）。"""
        requested = lang or self.lang or DEFAULT_LANG
        _, used_lang, fallback = self._select_template(requested)
        return {
            'code': self.code,
            'severity': self.severity.value,
            'message': self.render(lang=lang, include_location=include_location),
            'lang': used_lang,
            'fallback': fallback,
            'location': self.location if self.source is not None else None,
            'path': self.path,
            'params': _json_value(self.declaration.parameters()),
        }

    def sort_key(self) -> tuple[str, int, int]:
        """按源码位置排序（无位置排最后）。"""
        if self.source is None:
            return ('\uffff', 0, 0)
        s = self.source.start
        return (self.source.file.name, s.line, s.col)


class DiagnosticCollector:
    """诊断收集器：收集 :class:`Diagnostic`（词法/语法/语义阶段容错收集）。

    词法/语法/语义阶段不抛异常：错误以 Diagnostic 形式收集，边界处直接聚合。
    只读查询按 severity 分离：``errors`` / ``warnings`` / ``diagnostics``，
    ``has_errors`` 仅当含 ERROR 级别时成立（warning 不算错误）。

    构造时确定本次编译的渲染语言（显式 ``lang`` 优先，含不支持标签——
    渲染时按固定回退链回退；缺省按环境探测），``add`` 构造的诊断自动携带该语言。

    用法::

        collector = DiagnosticCollector()
        collector.add(DictDuplicateKey(name='a'), tf.source, path='a')
    """

    def __init__(self, lang: str | None = None) -> None:
        self._lang: str = lang or detect_lang()
        self._errors: list[Diagnostic] = []
        self._seen: set[tuple[str, str, str, str, str]] = set()

    @property
    def lang(self) -> str:
        """本次编译的渲染语言。"""
        return self._lang

    # ── 写入 ──────────────────────────────────────────

    def add(
        self,
        declaration: DiagnosticDeclaration,
        source: SourceRange | None = None,
        *,
        severity: Severity | None = None,
        path: str = '',
    ) -> None:
        """由声明实例构造并添加诊断（``severity`` 覆盖声明级别）。"""
        self._append(
            Diagnostic(declaration=declaration, source=source, path=path, severity_override=severity, lang=self._lang)
        )

    def extend(self, errors: Iterable[Diagnostic]) -> None:
        """批量添加诊断（未携带语言的诊断补齐为收集器语言）。"""
        for diagnostic in errors:
            self._append(diagnostic if diagnostic.lang is not None else replace(diagnostic, lang=self._lang))

    def _append(self, diagnostic: Diagnostic) -> None:
        """追加诊断；相同码 / 参数 / 位置 / 级别 / 语言的重复只保留首条。"""
        params = repr(sorted(diagnostic.declaration.parameters().items()))
        location = diagnostic.location if diagnostic.source is not None else diagnostic.path
        key = (
            diagnostic.code,
            params,
            location,
            diagnostic.severity.value,
            diagnostic.lang or '',
        )
        if key in self._seen:
            return
        self._seen.add(key)
        self._errors.append(diagnostic)

    # ── 只读查询（severity 感知：warning 与 error 语义分离） ──

    @property
    def diagnostics(self) -> list[Diagnostic]:
        """全部诊断的副本（含 ERROR / WARNING）。"""
        return self._errors.copy()

    @property
    def errors(self) -> list[Diagnostic]:
        """仅 ERROR 级别诊断的副本（warning 不算错误）。"""
        return [d for d in self._errors if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        """仅 WARNING 级别诊断的副本。"""
        return [d for d in self._errors if d.severity is Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        """是否含 ERROR 级别诊断（与 :class:`CompilationResult` 的 has_errors 语义一致）。"""
        return any(d.severity is Severity.ERROR for d in self._errors)

    @property
    def has_warnings(self) -> bool:
        """是否含 WARNING 级别诊断。"""
        return any(d.severity is Severity.WARNING for d in self._errors)

    # ── 容器协议 ──────────────────────────────────────

    def __iter__(self) -> Iterator[Diagnostic]:
        """迭代所有已收集的诊断。"""
        return iter(self._errors)

    def __len__(self) -> int:
        """已收集诊断数量（容器协议）。

        注意：空收集器为 falsy，可能被 ``collector or DiagnosticCollector()``
        静默替换；需要判断错误请用 ``has_errors``，需要数量请用
        ``len(collector.diagnostics)``。
        """
        return len(self._errors)
