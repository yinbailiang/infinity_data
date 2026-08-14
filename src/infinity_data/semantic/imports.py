"""导入语句解析：``!env`` / ``!file`` / ``!from``。

M3 授权模型：

- ``!env import``：变量必须列于 ``SandboxConfig.env``（否则 strict 抛
  :class:`SandboxError`，非 strict 警告）
- ``!file``：目标路径必须命中 ``allow_files`` glob 白名单
- ``!from``（模板导入）：目标路径必须命中 ``allow_templates`` glob 白名单；
  模板定义的实际加载由 :class:`SemanticAnalyzer` 完成
"""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from infinity_data.parser.models import (
    Document,
    EnvImportStmt,
    FileImportStmt,
    JsonPathIndex,
    JsonPathKey,
)
from infinity_data.sandbox import SandboxConfig, SandboxError
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
        sandbox: SandboxConfig | None = None,
    ) -> None:
        # env 兼容旧调用方式：直接提供映射时视为该映射即授权全集
        if sandbox is None:
            sandbox = SandboxConfig(env=dict(env)) if env is not None else SandboxConfig.deny_all()
        elif env is not None:
            sandbox = SandboxConfig(
                env={**sandbox.env, **dict(env)},
                allow_files=sandbox.allow_files,
                allow_templates=sandbox.allow_templates,
                strict=sandbox.strict,
            )
        self._sandbox: SandboxConfig = sandbox
        self._base_dir: Path = Path(base_dir) if base_dir is not None else Path.cwd()

    @property
    def sandbox(self) -> SandboxConfig:
        return self._sandbox

    @property
    def base_dir(self) -> Path:
        return self._base_dir

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
        if stmt.name in self._sandbox.env:
            namespace[name] = self._sandbox.env[stmt.name]
            return
        if self._sandbox.strict:
            raise SandboxError(f'环境变量 {stmt.name!r} 未在沙盒授权（!env import）', stmt.source)
        report(Severity.WARNING, f'环境变量 {stmt.name!r} 未在沙盒授权，已忽略', stmt.source)
        namespace[name] = ''

    def _resolve_file(
        self,
        stmt: FileImportStmt,
        namespace: dict[str, Any],
        report: ReportFn,
    ) -> None:
        """!file "path" [as fmt] import .path.to.key as alias, ..."""
        path = Path(stmt.file_path)
        if not path.is_absolute():
            path = self._base_dir / path

        if not self._sandbox.authorize_file(path, self._base_dir):
            if self._sandbox.strict:
                raise SandboxError(f'文件导入超出沙盒授权: {stmt.file_path}', stmt.source)
            report(Severity.WARNING, f'文件导入超出沙盒授权，已忽略: {stmt.file_path}', stmt.source)
            return

        if not path.exists():
            report(Severity.WARNING, f'导入文件不存在: {path}', stmt.source)
            return

        fmt = stmt.format or _FORMAT_MAP.get(path.suffix.lower(), 'json')
        data = self._read_data(path, fmt, report, stmt.source)
        if data is None:
            return

        for item in stmt.imports:
            try:
                value = self._resolve_json_path(data, item.json_path)
            except (KeyError, IndexError, TypeError):
                report(Severity.WARNING, f'无法解析导入路径: {path}', item.source)
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
    ) -> Path | None:
        """解析 !from 目标路径并做沙盒授权检查。

        - 相对路径以 base_dir（导入所在文件目录）为基准
        - strict 授权失败 → 抛 :class:`SandboxError`
        - 非 strict 授权失败 → 警告 + None
        """
        base = base_dir if base_dir is not None else self._base_dir
        path = Path(from_path)
        if not path.is_absolute():
            path = base / path

        if not self._sandbox.authorize_template(path, base):
            if self._sandbox.strict:
                raise SandboxError(f'模板导入超出沙盒授权: {from_path}', source)
            report(Severity.WARNING, f'模板导入超出沙盒授权，已忽略: {from_path}', source)
            return None
        return path

    # ── 辅助 ──────────────────────────────────────────

    def _read_data(
        self,
        path: Path,
        fmt: str,
        report: ReportFn,
        source: SourceRange,
    ) -> Any | None:
        """按格式读取文件内容。"""
        try:
            if fmt == 'json':
                with path.open(encoding='utf-8') as f:
                    return json.load(f)
            if fmt in ('yaml', 'yml'):
                try:
                    import yaml  # pyright: ignore[reportMissingModuleSource]
                except ImportError:
                    report(Severity.WARNING, f'yaml 支持需要安装 PyYAML: {path}', source)
                    return None
                with path.open(encoding='utf-8') as f:
                    return yaml.safe_load(f)
            if fmt == 'toml':
                with path.open('rb') as f:
                    return tomllib.load(f)
            report(Severity.WARNING, f'不支持的文件格式: {fmt}', source)
            return None
        except Exception as e:
            report(Severity.ERROR, f'读取文件失败 {path}: {e}', source)
            return None

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
