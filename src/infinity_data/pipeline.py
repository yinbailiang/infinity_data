"""编译流水线：源码字符串 → StdDocument / Python dict。

全链路流式：chars → RawTokenizer → FinalTokenizer → Parser → SemanticAnalyzer → Converter。

公共 API：
- :func:`compile_source` / :func:`load`：编译入口，返回 :class:`CompilationResult`
- :func:`safe_load`：零信任加载（deny_all 沙盒，禁止一切导入）
- :func:`check`：仅校验，返回诊断列表
- :func:`compile_to_dict`：编译为 StdDocument（不降维）
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from infinity_data.emit import reduce_object
from infinity_data.infra.file import DiskFile, File, MemFile
from infinity_data.parser.errors import ParseErrorCollector
from infinity_data.parser.models import Document
from infinity_data.parser.parser import Parser
from infinity_data.sandbox import Sandbox, SandboxConfig, SandboxError, Schema, SchemaError
from infinity_data.semantic.analyzer import SemanticAnalyzer
from infinity_data.semantic.imports import ImportResolver
from infinity_data.semantic.models import Diagnostic, Severity, StdDocument, StdObject
from infinity_data.semantic.registry import ConstraintRegistry
from infinity_data.tokenizer.errors import TokenizeErrorCollector
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.tokenizer import RawTokenizer


@dataclass
class CompilationResult:
    """一次编译的完整产物。"""

    document: StdDocument | None
    root: StdObject
    value: dict[str, Any]  # 降维后的纯 Python dict（尽力而为，即使有错误）
    diagnostics: list[Diagnostic] = field(default_factory=lambda: [])

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.diagnostics)

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.WARNING]


def _tokenize_and_parse(file: File) -> tuple[Document, list[Diagnostic]]:
    """词法 + 语法分析（字符流由 file.chars() 提供）。"""
    tokenize_collector = TokenizeErrorCollector()
    parse_collector = ParseErrorCollector()

    raw_tokens = RawTokenizer(
        file=file,
        error_collector=tokenize_collector,
    )
    tokens = FinalTokenizer(raw_tokens)
    parser = Parser(tokens, error_collector=parse_collector)
    doc = parser.parse()

    diagnostics: list[Diagnostic] = []
    for err in tokenize_collector:
        diagnostics.append(Diagnostic.from_error(err))
    for err in parse_collector:
        diagnostics.append(Diagnostic.from_error(err))
    return doc, diagnostics


def _effective_sandbox(
    sandbox: SandboxConfig | None,
    env: Mapping[str, str] | None,
) -> SandboxConfig:
    """合并 sandbox 与便捷 env 参数。

    - 两者均缺省 → deny_all（零信任，库默认）
    - 仅 env → 以 env 授权环境变量、其余关闭（兼容旧调用方式）
    - 均提供 → env 条目合并进 sandbox（env 优先）
    """
    if sandbox is None:
        return SandboxConfig(env=dict(env)) if env is not None else SandboxConfig.deny_all()
    if env is not None:
        return replace(sandbox, env={**sandbox.env, **dict(env)})
    return sandbox


def _compile_file(
    file: File,
    *,
    env: Mapping[str, str] | None = None,
    registry: ConstraintRegistry | None = None,
    sandbox: SandboxConfig | None = None,
    schema: Schema | None = None,
) -> CompilationResult:
    """编译统一入口：File（磁盘/内存）→ CompilationResult。"""
    text = file.read()
    # 空源码 → 空配置
    if not text.strip():
        return CompilationResult(
            document=None,
            root=StdObject(),
            value={},
            diagnostics=[],
        )

    doc, front_diagnostics = _tokenize_and_parse(file)

    sandbox_impl = Sandbox(
        config=_effective_sandbox(sandbox, env),
        base_dir=file.root_path,
    )
    resolver = ImportResolver(sandbox=sandbox_impl)
    analyzer = SemanticAnalyzer(registry=registry, import_resolver=resolver, schema=schema)
    document = analyzer.analyze(doc, file)

    diagnostics = sorted(
        [*front_diagnostics, *document.diagnostics],
        key=lambda d: d.sort_key(),
    )
    return CompilationResult(
        document=document,
        root=document.root,
        value=reduce_object(document.root),
        diagnostics=diagnostics,
    )


def compile_source(
    source: str,
    *,
    file_path: str = 'unknown',
    env: Mapping[str, str] | None = None,
    registry: ConstraintRegistry | None = None,
    sandbox: SandboxConfig | None = None,
    schema: Schema | None = None,
) -> CompilationResult:
    """编译源码字符串，返回 CompilationResult。

    Args:
        source: infd 源码文本
        file_path: 源码路径（诊断定位与相对导入基准）
        env: 环境变量便捷授权（等价于 SandboxConfig(env=env)，与 sandbox 合并）
        registry: 自定义约束注册表（None = 内置）
        sandbox: 沙盒配置（None = 零信任 deny_all）
        schema: 顶层模板约束

    Raises:
        SandboxError: 导入超出沙盒授权（strict 模式）
        SchemaError: 输出不符合顶层 schema 约束
    """
    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=source)
    return _compile_file(file, env=env, registry=registry, sandbox=sandbox, schema=schema)


def load(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    registry: ConstraintRegistry | None = None,
    sandbox: SandboxConfig | None = None,
    schema: Schema | None = None,
) -> CompilationResult:
    """加载 .infd/.inft 文件并编译。

    Args:
        path: 文件路径（相对导入以此为基准）
        env: 环境变量便捷授权（等价于 SandboxConfig(env=env)，与 sandbox 合并）
        registry: 自定义约束注册表（None = 内置）
        sandbox: 沙盒配置（None = 零信任 deny_all）
        schema: 顶层模板约束

    Raises:
        SandboxError: 导入超出沙盒授权（strict 模式）
        SchemaError: 输出不符合顶层 schema 约束
    """
    p = Path(path)
    file = DiskFile.from_fullpath(p)
    result = _compile_file(file, env=env, registry=registry, sandbox=sandbox, schema=schema)

    # 规范要求 utf-8 NO BOM
    if file.read().startswith('\ufeff'):
        result.diagnostics.append(
            Diagnostic(
                severity=Severity.WARNING,
                message='文件包含 BOM，规范要求 UTF-8 NO BOM 编码',
            )
        )
        result.diagnostics.sort(key=lambda d: d.sort_key())
    return result


def safe_load(
    path: str | Path,
    *,
    registry: ConstraintRegistry | None = None,
    schema: Schema | None = None,
) -> CompilationResult:
    """零信任加载：等价于 ``load(path, sandbox=SandboxConfig.deny_all())``。

    所有导入语句（``!env`` / ``!file`` / ``!from``）均报错。
    只允许纯字段定义、模板定义与字面量值。

    用途:
    - 读取沙盒配置文件（自举：SandboxConfig.from_dict）
    - 读取纯模板文件 (.inft)
    - 读取不需要外部资源的配置
    """
    return load(path, registry=registry, schema=schema, sandbox=SandboxConfig.deny_all())


def check(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    registry: ConstraintRegistry | None = None,
    sandbox: SandboxConfig | None = None,
    schema: Schema | None = None,
) -> list[Diagnostic]:
    """仅校验，不输出。沙盒/schema 违规转为 ERROR 诊断返回而非抛出。"""
    try:
        result = load(path, env=env, registry=registry, sandbox=sandbox, schema=schema)
    except (SandboxError, SchemaError) as e:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=e.message,
                source=e.source,
            )
        ]
    return result.diagnostics


def compile_to_dict(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    registry: ConstraintRegistry | None = None,
    sandbox: SandboxConfig | None = None,
    schema: Schema | None = None,
) -> StdDocument:
    """编译为 StdDocument（不经过降维），含 .root 与 .diagnostics。"""
    result = load(path, env=env, registry=registry, sandbox=sandbox, schema=schema)
    return result.document if result.document is not None else StdDocument()
