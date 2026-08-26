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

import hashlib
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
    VarStmt,
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
    '.txt': 'raw',
    '.text': 'raw',
    '.md': 'raw',
    '.log': 'raw',
}


def _import_hash(s: str) -> str:
    """导入真名哈希（§1.8，来源哈希，确定性）。"""
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


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

    def resolve(
        self,
        doc: Document,
        collector: DiagnosticCollector,
        *,
        base_dir: Path | None = None,
    ) -> dict[str, StdValue]:
        """解析所有导入语句（env/file），返回 namespace（StdValue）；诊断写入 ``collector``。

        ``base_dir``：``!file`` 相对路径的解析基准（就地解析，§1.8）——
        主文件传其目录；``.inft`` 模板文件传**该文件所在目录**（与 ``!from`` 一致）。
        """
        namespace: dict[str, StdValue] = {}
        for stmt in doc.statements:
            if isinstance(stmt, EnvImportStmt):
                self._resolve_env(stmt, namespace, collector)
            elif isinstance(stmt, FileImportStmt):
                self._resolve_file(stmt, namespace, collector, base_dir)
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
        """!env import NAME1 [as NEW1], NAME2 [as NEW2], ...

        未授权环境变量**总是失败**（无论 strict）：Sandbox.getenv 直接抛
        :class:`SandboxError`，不会退化为空字符串注入。
        """
        for item in stmt.items:
            name = item.alias or item.name
            raw = self._sandbox.getenv(item.name, source=item.source)
            self._bind(namespace, name, python_to_std(raw), collector, item.source)

    def _resolve_file(
        self,
        stmt: FileImportStmt,
        namespace: dict[str, StdValue],
        collector: DiagnosticCollector,
        base_dir: Path | None = None,
    ) -> None:
        """!file p"path" [as fmt] import .path.to.key as alias, ...（相对路径以 base_dir 解析）"""
        file = self._sandbox.open_file(stmt.file_path, source=stmt.source, base_dir=base_dir)
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

    def import_identities(self, doc: Document, *, base_dir: Path | None = None) -> dict[str, str]:
        """doc 中每个 $ 绑定的**导入真名**（来源哈希，不含运行时值；§1.8）。

        - env: ``SHA256("env" || 变量名)``
        - file: ``SHA256(fmt || jsonpath || 文件内容哈希)``（文件被拒/不可读 → 该绑定无真名）
        - var: ``SHA256(canon(值表达式) || path)``

        真名是身份/签名维度：相同来源 → 相同真名，与机器/环境无关
        （env 的**值**不进哈希，否则身份随环境漂移）。供模板身份纳入数据依赖（§2.5）。
        """
        out: dict[str, str] = {}
        for stmt in doc.statements:
            if isinstance(stmt, EnvImportStmt):
                for item in stmt.items:
                    out[item.alias or item.name] = _import_hash(f'env:{item.name}')
            elif isinstance(stmt, FileImportStmt):
                file = self._sandbox.open_file(stmt.file_path, source=stmt.source, base_dir=base_dir)
                if file is None:
                    continue
                try:
                    content = file.content_hash()
                except OSError:
                    continue
                fmt = stmt.format or _FORMAT_MAP.get(Path(stmt.file_path).suffix.lower(), 'json')
                for item in stmt.imports:
                    path = ''.join(seg.canonical() for seg in item.json_path) or '.'
                    out[item.alias] = _import_hash(f'file:{fmt}|{path}|{content}')
            elif isinstance(stmt, VarStmt):
                path = ''.join(seg.canonical() for seg in stmt.json_path) or '.'
                out[stmt.alias] = _import_hash(f'var:{stmt.value.canonical()}|{path}')
        return out

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
            if fmt == 'raw':
                # raw：直接导入字符串（不做任何解析，保留文件原文）
                return text
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
