"""导入语句解析：``!env`` / ``!file`` / ``!from``。

所有系统访问经 :class:`Sandbox` 中介：

- ``!env import``：变量经 ``Sandbox.getenv`` 授权查询
- ``!file``：数据文件经 ``Sandbox.open_file`` 产出 File 后解析
- ``!from``（模板导入）：模板文件经 ``Sandbox.open_template`` 产出 File，
  模板定义的实际加载由 :class:`SemanticAnalyzer` 完成
"""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from infinity_data.infra.file import File
from infinity_data.parser.models import (
    Document,
    EnvImportStmt,
    FileImportStmt,
    JsonPathIndex,
    JsonPathKey,
)
from infinity_data.sandbox import Sandbox, SandboxConfig
from infinity_data.semantic.models import Severity
from infinity_data.tokenizer.models.raw_tokens import SourceRange

ReportFn = Callable[[Severity, str, SourceRange | None], None]

_FORMAT_MAP: dict[str, str] = {
    '.json': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.toml': 'toml',
}


class ImportResolver:
    """解析导入语句，产出 ``$`` 引用命名空间（alias → Python 值）。"""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        base_dir: str | os.PathLike[str] | None = None,
        sandbox: Sandbox | None = None,
    ) -> None:
        # env 兼容旧调用方式：直接提供映射时视为该映射即授权全集
        if sandbox is None:
            config = SandboxConfig(env=dict(env)) if env is not None else SandboxConfig.deny_all()
            sandbox = Sandbox(
                config=config,
                base_dir=Path(base_dir) if base_dir is not None else Path.cwd(),
            )
        elif env is not None:
            config = SandboxConfig(
                env={**sandbox.config.env, **dict(env)},
                allow_files=sandbox.config.allow_files,
                allow_templates=sandbox.config.allow_templates,
                strict=sandbox.config.strict,
            )
            sandbox = Sandbox(config=config, base_dir=sandbox.base_dir)
        self._sandbox: Sandbox = sandbox

    @property
    def sandbox(self) -> Sandbox:
        return self._sandbox

    @property
    def base_dir(self) -> Path:
        return self._sandbox.base_dir

    def resolve(self, doc: Document, report: ReportFn) -> dict[str, Any]:
        """解析所有导入语句（env/file），返回 namespace。"""
        namespace: dict[str, Any] = {}
        for stmt in doc.statements:
            if isinstance(stmt, EnvImportStmt):
                self._resolve_env(stmt, namespace, report)
            elif isinstance(stmt, FileImportStmt):
                self._resolve_file(stmt, namespace, report)
        return namespace

    # ── 各类导入 ──────────────────────────────────────

    def _resolve_env(
        self,
        stmt: EnvImportStmt,
        namespace: dict[str, Any],
        report: ReportFn,
    ) -> None:
        """!env import NAME [as NEW_NAME]"""
        name = stmt.alias or stmt.name
        value = self._sandbox.getenv(stmt.name, source=stmt.source)
        if value is None:
            report(Severity.WARNING, f'环境变量 {stmt.name!r} 未在沙盒授权，已忽略', stmt.source)
            namespace[name] = ''
            return
        namespace[name] = value

    def _resolve_file(
        self,
        stmt: FileImportStmt,
        namespace: dict[str, Any],
        report: ReportFn,
    ) -> None:
        """!file "path" [as fmt] import .path.to.key as alias, ..."""
        file = self._sandbox.open_file(stmt.file_path, source=stmt.source)
        if file is None:
            report(Severity.WARNING, f'文件导入超出沙盒授权，已忽略: {stmt.file_path}', stmt.source)
            return

        fmt = stmt.format or _FORMAT_MAP.get(Path(stmt.file_path).suffix.lower(), 'json')
        try:
            text = file.read()
        except OSError:
            report(Severity.WARNING, f'导入文件不存在: {file.name}', stmt.source)
            return

        data = self._parse_data(text, fmt, report, stmt.source)
        if data is None:
            return

        for item in stmt.imports:
            try:
                value = self._resolve_json_path(data, item.json_path)
            except (KeyError, IndexError, TypeError):
                report(Severity.WARNING, f'无法解析导入路径: {file.name}', item.source)
                continue
            namespace[item.alias] = value

    # ── 模板导入路径解析（!from 由 SemanticAnalyzer 使用）──

    def resolve_template_path(
        self,
        from_path: str,
        *,
        base_dir: Path | None,
        source: SourceRange | None,
        report: ReportFn,
    ) -> File | None:
        """!from 目标：经沙盒授权产出 File（相对路径以导入所在文件目录解析）。"""
        file = self._sandbox.open_template(from_path, base_dir=base_dir, source=source)
        if file is None:
            report(Severity.WARNING, f'模板导入超出沙盒授权，已忽略: {from_path}', source)
        return file

    # ── 辅助 ──────────────────────────────────────────

    def _parse_data(
        self,
        text: str,
        fmt: str,
        report: ReportFn,
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
                    report(Severity.WARNING, 'yaml 支持需要安装 PyYAML', source)
                    return None
                return yaml.safe_load(text)
            if fmt == 'toml':
                return tomllib.loads(text)
            report(Severity.WARNING, f'不支持的文件格式: {fmt}', source)
            return None
        except Exception as e:
            report(Severity.ERROR, f'解析数据失败: {e}', source)
            return None

    # ── 辅助 ──────────────────────────────────────────

    @staticmethod
    def _resolve_json_path(data: Any, segments: list[JsonPathKey | JsonPathIndex]) -> Any:
        """按结构化路径段定位数据；空路径 = 整个文件。"""
        current = data
        for seg in segments:
            match seg:
                case JsonPathKey(key=k):
                    current = current[k]
                case JsonPathIndex(index=i):
                    current = current[i]
        return current
