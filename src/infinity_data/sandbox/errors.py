"""沙盒安全异常体系（自有，独立于统一诊断模型）。

错误模型：
- 词法/语法/语义错误统一为 :class:`Diagnostic`（纯数据，从不抛异常）
- 沙盒错误必须**中止编译**（控制流），故保留异常；携带**诊断声明实例**
  （:class:`~infinity_data.infra.diagnostics.DiagnosticDeclaration`）与源码位置，
  由编译核心（``infinity_data.pipeline``）捕获并转换为 ERROR 诊断，返回空文档
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Mapping

from infinity_data.infra.diagnostics import (
    Diagnostic,
    DiagnosticDeclaration,
    Severity,
    detect_lang,
    registry,
)
from infinity_data.infra.location import SourceRange, format_location

__all__ = [
    'SandboxEnvUnauthorized',
    'SandboxEnvNotSet',
    'SandboxAccessDenied',
    'SandboxFileMissing',
    'SchemaUndefinedTemplate',
    'SchemaFailed',
    'SchemaExtraFields',
    'SchemaExtraFieldsLenient',
    'SchemaMissingRequired',
    'SchemaMissingOptional',
    'SandboxError',
    'EnvNotAuthorizedError',
    'EnvNotSetError',
    'AccessDeniedError',
    'FileMissingError',
    'SchemaError',
]


@registry.register
@dataclass(frozen=True)
class SandboxEnvUnauthorized(DiagnosticDeclaration):
    """环境变量未授权。"""

    code: ClassVar[str] = 'sandbox.env_unauthorized'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}环境变量 {name!r} 未在沙盒授权（!env import）',
        'en-US': '{location_prefix}environment variable {name!r} is not authorized (!env import)',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class SandboxEnvNotSet(DiagnosticDeclaration):
    """环境变量已授权但未设置。"""

    code: ClassVar[str] = 'sandbox.env_not_set'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}环境变量 {name!r} 已授权但当前进程未设置',
        'en-US': '{location_prefix}environment variable {name!r} is authorized but not set in this process',
    }
    name: str


@registry.register
@dataclass(frozen=True)
class SandboxAccessDenied(DiagnosticDeclaration):
    """导入超出沙盒授权。"""

    code: ClassVar[str] = 'sandbox.access_denied'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}{target} 目标超出沙盒授权: {path_src}',
        'en-US': '{location_prefix}{target} target denied by sandbox: {path_src}',
    }
    target: Literal['!file', '!from']
    path_src: str


@registry.register
@dataclass(frozen=True)
class SandboxFileMissing(DiagnosticDeclaration):
    """白名单内但目标不存在。"""

    code: ClassVar[str] = 'sandbox.file_missing'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{location_prefix}{target} 目标不存在或不是文件: {path_src}',
        'en-US': '{location_prefix}{target} target is missing or not a file: {path_src}',
    }
    target: Literal['!file', '!from']
    path_src: str


@registry.register
@dataclass(frozen=True)
class SchemaUndefinedTemplate(DiagnosticDeclaration):
    """schema 模板未定义。"""

    code: ClassVar[str] = 'schema.undefined_template'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '未定义的 schema 模板 {template!r}',
        'en-US': 'undefined schema template {template!r}',
    }
    template: str


@registry.register
@dataclass(frozen=True)
class SchemaFailed(DiagnosticDeclaration):
    """顶层 schema 校验失败（汇总）。"""

    code: ClassVar[str] = 'schema.failed'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '顶层 schema 校验失败（{count} 个错误）',
        'en-US': 'top-level schema validation failed ({count} error(s))',
    }
    count: int


@registry.register
@dataclass(frozen=True)
class SchemaExtraFields(DiagnosticDeclaration):
    """顶层 schema 不允许额外字段。"""

    code: ClassVar[str] = 'schema.extra_fields'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '顶层 schema 不允许额外字段: {fields}',
        'en-US': 'top-level schema does not allow extra fields: {fields}',
    }
    fields: list[str]


@registry.register
@dataclass(frozen=True)
class SchemaExtraFieldsLenient(DiagnosticDeclaration):
    """顶层 schema 存在额外字段（保留）。"""

    code: ClassVar[str] = 'schema.extra_fields_lenient'
    severity: ClassVar[Severity] = Severity.WARNING
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '顶层 schema 存在额外字段（已保留）: {fields}',
        'en-US': 'top-level schema has extra fields (kept): {fields}',
    }
    fields: list[str]


@registry.register
@dataclass(frozen=True)
class SchemaMissingRequired(DiagnosticDeclaration):
    """顶层 schema 缺少必填字段。"""

    code: ClassVar[str] = 'schema.missing_required'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}顶层 schema 缺少必填字段 {field!r}（模板 {template}）',
        'en-US': '{path_prefix}top-level schema is missing required field {field!r} (template {template})',
    }
    field: str
    template: str


@registry.register
@dataclass(frozen=True)
class SchemaMissingOptional(DiagnosticDeclaration):
    """顶层 schema 缺少可选字段。"""

    code: ClassVar[str] = 'schema.missing_optional'
    severity: ClassVar[Severity] = Severity.ERROR
    templates: ClassVar[Mapping[str, str]] = {
        'zh-CN': '{path_prefix}顶层 schema 缺少可选字段 {field!r}（模板 {template}；用 `!` 允许缺失）',
        'en-US': '{path_prefix}top-level schema is missing optional field {field!r} (template {template}; use `!` to allow absence)',
    }
    field: str
    template: str


class SandboxError(Exception):
    """沙盒安全异常基类（自有体系）：携带诊断声明实例 + 源码位置。

    ``diagnostics``：可选的结构化诊断列表（schema 校验等多错误场景）；
    非空时调用方应优先逐条并入收集器。
    """

    def __init__(
        self,
        declaration: DiagnosticDeclaration,
        source: SourceRange | None = None,
        *,
        diagnostics: list[Diagnostic] | None = None,
    ) -> None:
        super().__init__(declaration.code)
        self.declaration: DiagnosticDeclaration = declaration
        self.source: SourceRange | None = source
        self.diagnostics: list[Diagnostic] = diagnostics or []

    @property
    def code(self) -> str:
        """稳定错误码（来自声明）。"""
        return self.declaration.code

    @property
    def location(self) -> str:
        """格式化的源码位置。"""
        return format_location(self.source)

    @property
    def message(self) -> str:
        """渲染后的用户消息（含位置前缀，按环境探测语言）。

        携带多条结构化诊断时按行拼接全部消息，避免把多条错误压成一个字符串；
        无附加诊断时回退到 ``declaration`` 的摘要消息。
        """
        if not self.diagnostics:
            return Diagnostic(declaration=self.declaration, source=self.source, lang=detect_lang()).render()
        return '\n'.join(self.messages)

    @property
    def messages(self) -> list[str]:
        """逐条渲染的用户消息（无附加诊断时返回单条摘要）。"""
        if not self.diagnostics:
            return [self.message]
        lang = detect_lang()
        return [d.render(lang=d.lang or lang) for d in self.diagnostics]

    def __str__(self) -> str:
        return self.message


class EnvNotAuthorizedError(SandboxError):
    """``!env`` 引用的变量未在沙盒授权。"""

    def __init__(self, name: str, source: SourceRange | None = None) -> None:
        super().__init__(SandboxEnvUnauthorized(name=name), source)


class EnvNotSetError(SandboxError):
    """变量已授权但当前进程未设置。"""

    def __init__(self, name: str, source: SourceRange | None = None) -> None:
        super().__init__(SandboxEnvNotSet(name=name), source)


class AccessDeniedError(SandboxError):
    """文件/模板导入超出 glob 白名单。"""

    def __init__(self, target: Literal['!file', '!from'], path: str, source: SourceRange | None = None) -> None:
        super().__init__(SandboxAccessDenied(target=target, path_src=path), source)


class FileMissingError(SandboxError):
    """白名单内但目标不存在（``strict`` 模式下中止编译）。"""

    def __init__(self, target: Literal['!file', '!from'], path: str, source: SourceRange | None = None) -> None:
        super().__init__(SandboxFileMissing(target=target, path_src=path), source)


class SchemaError(SandboxError):
    """顶层 schema 校验失败（中止编译）；以声明实例区分具体原因。"""

    pass
