"""导入语句求解：``!env`` / ``!file`` / ``!from`` 的系统访问。

所有系统访问经 :class:`Sandbox` 中介：

- ``!env import``：变量经 ``Sandbox.getenv`` 授权查询
- ``!file``：数据文件经 ``Sandbox.open_file`` 产出 File 后解析
- ``!from``（模板导入）：模板文件经 ``Sandbox.open_template`` 产出 File，
  模板定义的实际加载由 Phase 1 的 :class:`TemplateGraphResolver` 完成

本层产出 ``$`` 引用命名空间（alias → StdValue）：外部数据经
:func:`python_to_std` 直接转为 AST，与 ``!var`` 注入统一；诊断直接写入调用方
注入的共享 :class:`DiagnosticCollector`（与 resolver / builder 的收集器模式统一）。
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from infinity_data.infra.diagnostics import Diagnostic, DiagnosticCollector, Severity
from infinity_data.infra.file import File
from infinity_data.parser import (
    Document,
    EnvImportStmt,
    FileImportStmt,
)
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.jsonpath import apply_json_path
from infinity_data.semantic.std import StdValue, python_to_std
from infinity_data.tokenizer.models.raw_tokens import SourceRange

_FORMAT_MAP: dict[str, str] = {
    '.json': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.toml': 'toml',
}


class ImportResolver:
    """解析导入语句，产出 ``$`` 引用命名空间（alias → Python 值）。

    Args:
        sandbox: 沙盒中介（授权 / 拒绝一切系统访问）。None = 零信任 deny_all。
    """

    def __init__(self, *, sandbox: Sandbox | None = None) -> None:
        # 零信任默认：未提供沙盒时拒绝一切系统访问（库默认 deny_all）
        self._sandbox = sandbox or Sandbox(config=SandboxConfig.deny_all(), base_dir=Path.cwd())

    @property
    def sandbox(self) -> Sandbox:
        return self._sandbox

    @property
    def base_dir(self) -> Path:
        return self._sandbox.base_dir

    def resolve(self, doc: Document, collector: DiagnosticCollector) -> dict[str, StdValue]:
        """解析所有导入语句（env/file），返回 namespace（StdValue）；诊断写入 ``collector``。"""
        namespace: dict[str, StdValue] = {}
        for stmt in doc.statements:
            if isinstance(stmt, EnvImportStmt):
                self._resolve_env(stmt, namespace, collector)
            elif isinstance(stmt, FileImportStmt):
                self._resolve_file(stmt, namespace, collector)
        return namespace

    def _bind(
        self,
        namespace: dict[str, StdValue],
        name: str,
        value: StdValue,
        collector: DiagnosticCollector,
        source: SourceRange | None,
    ) -> None:
        """绑定 ``$`` 命名空间条目；重复 alias → ERROR 并拒绝覆盖（保留先到者）。

        与模板 scope 一致：``$`` 命名空间内不允许隐式的"后者覆盖前者"。
        """
        if name in namespace:
            collector.add(Diagnostic(Severity.ERROR, 'namespace.duplicate', {'name': name}, source))
            return
        namespace[name] = value

    # ── 各类导入 ──────────────────────────────────────

    def _resolve_env(
        self,
        stmt: EnvImportStmt,
        namespace: dict[str, StdValue],
        collector: DiagnosticCollector,
    ) -> None:
        """!env import NAME [as NEW_NAME]

        未授权环境变量**总是失败**（无论 strict）：Sandbox.getenv 直接抛
        :class:`SandboxError`，不会退化为空字符串注入。
        """
        name = stmt.alias or stmt.name
        raw = self._sandbox.getenv(stmt.name, source=stmt.source)
        self._bind(namespace, name, python_to_std(raw), collector, stmt.source)

    def _resolve_file(
        self,
        stmt: FileImportStmt,
        namespace: dict[str, StdValue],
        collector: DiagnosticCollector,
    ) -> None:
        """!file "path" [as fmt] import .path.to.key as alias, ..."""
        file = self._sandbox.open_file(stmt.file_path, source=stmt.source)
        if file is None:
            collector.add(Diagnostic(Severity.WARNING, 'import.file_denied', {'path_src': stmt.file_path}, stmt.source))
            return

        fmt = stmt.format or _FORMAT_MAP.get(Path(stmt.file_path).suffix.lower(), 'json')
        try:
            text = file.read()
        except OSError:
            collector.add(Diagnostic(Severity.WARNING, 'import.file_missing', {'name': file.name}, stmt.source))
            return

        data = self._parse_data(text, fmt, collector, stmt.source)
        if data is None:
            return
        # 外部数据直接转 AST：统一处理流程（JSON path / 约束 / 输出全部操作 StdValue）
        root = python_to_std(data)

        for item in stmt.imports:
            try:
                value = apply_json_path(root, item.json_path)
            except (KeyError, IndexError, TypeError):
                collector.add(Diagnostic(Severity.WARNING, 'import.path_failed', {'name': file.name}, item.source))
                continue
            self._bind(namespace, item.alias, value, collector, item.source)

    # ── 模板导入路径解析（!from 由 TemplateGraphResolver 使用）──

    def resolve_template_path(
        self,
        from_path: str,
        *,
        base_dir: Path | None,
        source: SourceRange | None,
        collector: DiagnosticCollector,
    ) -> File | None:
        """!from 目标：经沙盒授权产出 File（相对路径以导入所在文件目录解析）。"""
        file = self._sandbox.open_template(from_path, base_dir=base_dir, source=source)
        if file is None:
            collector.add(Diagnostic(Severity.WARNING, 'import.template_denied', {'path_src': from_path}, source))
        return file

    # ── 辅助 ──────────────────────────────────────────

    def _parse_data(
        self,
        text: str,
        fmt: str,
        collector: DiagnosticCollector,
        source: SourceRange,
    ) -> Any | None:
        """按格式解析数据内容（文本 loads）。"""
        try:
            if fmt == 'json':
                return json.loads(text)
            if fmt in ('yaml', 'yml'):
                try:
                    import yaml  # pyright: ignore[reportMissingModuleSource]
                except ImportError:
                    collector.add(Diagnostic(Severity.WARNING, 'import.yaml_missing', {}, source))
                    return None
                return yaml.safe_load(text)
            if fmt == 'toml':
                return tomllib.loads(text)
            collector.add(Diagnostic(Severity.WARNING, 'import.unsupported_format', {'format': fmt}, source))
            return None
        except Exception as e:
            collector.add(Diagnostic(Severity.ERROR, 'import.parse_failed', {'error': e}, source))
            return None
