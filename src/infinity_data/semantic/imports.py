"""导入语句解析：``!env`` / ``!file`` / ``!from``。

M2 提供基础实现：

- ``!env import``：从进程环境变量或显式 env 映射取值
- ``!file``：本地文件读取（json / toml 内建；yaml 需可选依赖 PyYAML）
- ``!from``（模板导入）：占位警告，M3 与 SandboxConfig 一并实现

M3 将引入授权模型（env 白名单、allow_files/allow_templates glob、strict 模式）。
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
    TemplateImportStmt,
)
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
    ) -> None:
        self._env: Mapping[str, str] = env if env is not None else os.environ
        self._base_dir: Path = Path(base_dir) if base_dir is not None else Path.cwd()

    def resolve(self, doc: Document, report: ReportFn) -> dict[str, Any]:
        """解析所有导入语句，返回 namespace。"""
        namespace: dict[str, Any] = {}
        for stmt in doc.statements:
            if isinstance(stmt, EnvImportStmt):
                self._resolve_env(stmt, namespace)
            elif isinstance(stmt, FileImportStmt):
                self._resolve_file(stmt, namespace, report)
            elif isinstance(stmt, TemplateImportStmt):
                report(
                    Severity.WARNING,
                    f'模板导入 !from 尚未实现（M3）: {stmt.from_path}',
                    stmt.source,
                )
        return namespace

    # ── 各类导入 ──────────────────────────────────────

    def _resolve_env(self, stmt: EnvImportStmt, namespace: dict[str, Any]) -> None:
        """!env import NAME [as NEW_NAME]"""
        name = stmt.alias or stmt.name
        namespace[name] = self._env.get(stmt.name, '')

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
