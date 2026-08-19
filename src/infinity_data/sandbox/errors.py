"""沙盒安全异常体系（自有，独立于统一诊断模型）。

错误模型：
- 词法/语法/语义错误统一为 :class:`Diagnostic`（纯数据，从不抛异常）
- 沙盒错误必须**中止编译**（控制流），故保留异常；携带 ``code/params/source``，
  由编译核心（``infinity_data.pipeline``）捕获并转换为 ERROR 诊断，返回空文档
"""

from __future__ import annotations

from typing import Any

from infinity_data.infra.diagnostics import diagnostic_define, register_diagnostic_define, render_message
from infinity_data.infra.location import SourceRange, format_location

__all__ = [
    'SandboxError',
    'EnvNotAuthorizedError',
    'EnvNotSetError',
    'AccessDeniedError',
    'SchemaError',
]

register_diagnostic_define(
    diagnostic_define(
        'sandbox.env_unauthorized',
        '[{location}] 环境变量 {name!r} 未在沙盒授权（!env import）',
        en='[{location}] environment variable {name!r} is not authorized (!env import)',
    ),
    diagnostic_define(
        'sandbox.env_not_set',
        '[{location}] 环境变量 {name!r} 已授权但当前进程未设置',
        en='[{location}] environment variable {name!r} is authorized but not set in this process',
    ),
    diagnostic_define(
        'sandbox.access_denied',
        '[{location}] {label}超出沙盒授权: {path_src}',
        en='[{location}] {label} denied by sandbox: {path_src}',
    ),
    diagnostic_define('schema.undefined_template', '未定义的 schema 模板 {template!r}', en='undefined schema template {template!r}'),
    diagnostic_define('schema.failed', '顶层 schema 校验失败: {detail}', en='top-level schema validation failed: {detail}'),
    diagnostic_define('schema.extra_fields', '顶层 schema 不允许额外字段: {fields}', en='top-level schema does not allow extra fields: {fields}'),
    diagnostic_define('schema.extra_fields_lenient', '顶层 schema 存在额外字段（已保留）: {fields}'),
    diagnostic_define('schema.missing_required', '{path_prefix}顶层 schema 缺少必填字段 {field!r}（模板 {template}）'),
)


class SandboxError(Exception):
    """沙盒安全异常基类（自有体系）。"""

    def __init__(
        self,
        code: str,
        params: dict[str, Any] | None = None,
        source: SourceRange | None = None,
    ) -> None:
        super().__init__(code)
        self.code: str = code
        self.params: dict[str, Any] = params or {}
        self.source: SourceRange | None = source

    @property
    def location(self) -> str:
        return format_location(self.source)

    @property
    def message(self) -> str:
        return render_message(self.code, self.params, location=self.location)

    def __str__(self) -> str:
        return self.message


class EnvNotAuthorizedError(SandboxError):
    """``!env`` 引用的变量未在沙盒授权。"""

    def __init__(self, name: str, source: SourceRange | None = None) -> None:
        super().__init__('sandbox.env_unauthorized', {'name': name}, source)


class EnvNotSetError(SandboxError):
    """变量已授权但当前进程未设置。"""

    def __init__(self, name: str, source: SourceRange | None = None) -> None:
        super().__init__('sandbox.env_not_set', {'name': name}, source)


class AccessDeniedError(SandboxError):
    """文件/模板导入超出 glob 白名单。"""

    def __init__(self, label: str, path: str, source: SourceRange | None = None) -> None:
        super().__init__('sandbox.access_denied', {'label': label, 'path_src': path}, source)


class SchemaError(SandboxError):
    """顶层 schema 校验失败（中止编译）；以 ``code`` 区分具体原因。"""

    pass
