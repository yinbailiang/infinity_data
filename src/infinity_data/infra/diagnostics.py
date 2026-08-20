"""统一诊断模型（所有阶段共用）与容错收集器。

- :class:`Severity` / :class:`Diagnostic`：稳定错误码 + 结构化参数 + 渲染消息。
  词法/语法/语义阶段统一使用；沙盒异常（见 :mod:`infinity_data.sandbox.errors`）
  经 ``check()`` 边界转换为 Diagnostic。
- :class:`DiagnosticCollector`：前端容错收集器（词法/语法错误作为 Diagnostic
  收集，从不抛异常）。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from infinity_data.infra.location import SourceRange, format_location

__all__ = [
    'DEFAULT_LANG',
    'Severity',
    'Diagnostic',
    'DiagnosticDefine',
    'diagnostic_define',
    'register_diagnostic_define',
    'render_message',
    'DiagnosticCollector',
]

DEFAULT_LANG = 'zh'
"""默认渲染语言。"""


class Severity(Enum):
    """诊断严重级别。"""

    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'


@dataclass(frozen=True)
class Diagnostic:
    """统一诊断：稳定错误码 + 结构化参数 + 渲染消息。

    - ``code``：稳定错误码（如 ``"template.undefined"``），测试/工具据此匹配
    - ``params``：结构化参数；``message`` 为派生属性，由注册表按语言渲染
    - ``lang``：渲染语言（None = 默认语言）；模板缺失时回退默认语言
    """

    severity: Severity
    code: str
    params: Mapping[str, Any] = field(default_factory=dict[str, Any])
    source: SourceRange | None = None
    path: str = ''
    lang: str | None = None

    @property
    def location(self) -> str:
        return format_location(self.source)

    @property
    def message(self) -> str:
        """按错误码 + 参数 + 语言渲染的人类可读消息。"""
        return render_message(
            self.code, self.params, location=self.location, path=self.path, lang=self.lang or DEFAULT_LANG
        )

    def sort_key(self) -> tuple[str, int, int]:
        """按源码位置排序。"""
        if self.source is None:
            return ('\uffff', 0, 0)
        s = self.source.start
        return (self.source.file.name, s.line, s.col)


@dataclass(frozen=True)
class DiagnosticDefine:
    """诊断定义：稳定错误码 + 语言模板。

    - ``code``：稳定错误码（如 ``"template.undefined"``）
    - ``template``：默认语言（``DEFAULT_LANG``）模板
    - ``translations``：其他语言模板（语言码 → 模板），缺失时回退默认模板
    """

    code: str
    template: str
    translations: Mapping[str, str] = field(default_factory=dict[str, str])

    def template_for(self, lang: str = DEFAULT_LANG) -> str:
        """取指定语言的模板；缺失回退默认模板。"""
        if lang == DEFAULT_LANG:
            return self.template
        return self.translations.get(lang, self.template)


_DIAGNOSTIC_DEFINE_REGISTRY: dict[str, DiagnosticDefine] = {}
"""诊断定义注册表（code → 定义）。"""


def diagnostic_define(code: str, template: str, **translations: str) -> DiagnosticDefine:
    """构造诊断定义（``translations`` 为其他语言模板，如 ``en=...``）。"""
    return DiagnosticDefine(code=code, template=template, translations=translations)


def register_diagnostic_define(*defines: DiagnosticDefine) -> None:
    """注册诊断定义（重复 code 后者覆盖）。"""
    for d in defines:
        _DIAGNOSTIC_DEFINE_REGISTRY[d.code] = d


def registered_diagnostic_defines() -> Mapping[str, DiagnosticDefine]:
    """已注册定义表（只读视图）。"""
    return _DIAGNOSTIC_DEFINE_REGISTRY


def render_message(
    code: str,
    params: Mapping[str, Any],
    *,
    location: str = '<unknown>',
    path: str = '',
    lang: str = DEFAULT_LANG,
) -> str:
    """按错误码 + 参数 + 语言渲染消息；未知错误码原样返回错误码本身。"""
    d = _DIAGNOSTIC_DEFINE_REGISTRY.get(code)
    if d is None:
        return code
    template = d.template_for(lang)
    context: dict[str, Any] = {
        'location': location,
        'path': path,
        'path_prefix': f'{path}: ' if path else '',
        **params,
    }
    try:
        return template.format(**context)
    except (KeyError, IndexError, ValueError, AttributeError):
        return code


class DiagnosticCollector:
    """诊断收集器：收集 :class:`Diagnostic`（词法/语法/语义阶段容错收集）。

    词法/语法/语义阶段不抛异常：错误以 Diagnostic 形式收集，边界处直接聚合。
    只读查询按 severity 分离：``errors`` / ``warnings`` / ``diagnostics``，
    ``has_errors`` 仅当含 ERROR 级别时成立（warning 不算错误）。

    用法::

        collector = DiagnosticCollector()
        tokenizer = RawTokenizer(file, error_collector=collector)
        ...
        for err in collector:
            print(err.code)
    """

    def __init__(self) -> None:
        self._errors: list[Diagnostic] = []

    # ── 写入 ──────────────────────────────────────────

    def add(self, error: Diagnostic) -> None:
        """添加一个诊断。"""
        self._errors.append(error)

    def extend(self, errors: Iterable[Diagnostic]) -> None:
        """批量添加诊断。"""
        self._errors.extend(errors)

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

        空收集器为 falsy（``bool(collector)`` = 是否收集到任何诊断，含 warning；
        区别于 ``has_errors`` 的"是否含 ERROR"）——
        因此缺省构造**不可用 ``error_collector or DiagnosticCollector()``**：
        空收集器会被 `or` 判定为假而静默替换，丢弃调用方传入的收集器。
        """
        return len(self._errors)
