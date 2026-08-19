"""编译流水线：源码字符串 → StdDocument / Python dict。

全链路流式：chars → RawTokenizer → FinalTokenizer → Parser → AstBuilder → Executor → Converter。

公共 API：
- :func:`load` / :func:`compile_source`：编译入口，返回 :class:`CompilationResult`
- :func:`safe_load`：零信任加载（deny_all 沙盒，禁止一切导入）
- :func:`check`：仅校验，返回诊断列表
- :func:`compile_document`：编译为 StdDocument（不降维）

共享选项（env/sandbox/registry/schema）统一由 :class:`CompileOptions` 承载，
各入口不再逐参数重复声明/转发。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path
from typing import Any

from infinity_data.emit import reduce_object
from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.infra.file import DiskFile, File, MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig, SandboxError, Schema
from infinity_data.semantic.builder import AstBuilder
from infinity_data.semantic.imports import ImportResolver
from infinity_data.semantic.models import StdDocument
from infinity_data.semantic.registry import ConstraintRegistry
from infinity_data.semantic.resolver import TemplateGraphResolver


@dataclass(frozen=True)
class CompileOptions:
    """一次编译的共享选项（各公共入口的统一参数载体）。

    - ``env``：环境变量便捷授权，等价于 ``SandboxConfig(env=...)``，与 ``sandbox`` 合并
    - ``sandbox``：沙盒配置；``None`` = 零信任（deny_all，库默认）
    - ``registry``：自定义约束注册表；``None`` = 内置
    - ``schema``：顶层模板约束；``None`` = 不校验
    """

    env: Mapping[str, str] | None = None
    sandbox: SandboxConfig | None = None
    registry: ConstraintRegistry | None = None
    schema: Schema | None = None

    def effective_sandbox(self) -> SandboxConfig:
        """env 合并进 sandbox 得实际生效配置；两者均缺省 → deny_all（零信任，库默认）。"""
        if self.sandbox is None:
            return SandboxConfig(env=dict(self.env)) if self.env is not None else SandboxConfig.deny_all()
        if self.env is not None:
            return replace(self.sandbox, env={**self.sandbox.env, **dict(self.env)})
        return self.sandbox


@dataclass
class CompilationResult:
    """一次编译的完整产物（根产物 + 诊断）。

    - ``document``：:class:`StdDocument`（root / templates / scope / diagnostics）
    - ``root`` / ``value``：由 ``document`` 派生（惰性）——降维属 emit 层职责，
      编译阶段不急于产出，访问时经 :mod:`infinity_data.emit` 计算
    """

    document: StdDocument
    diagnostics: list[Diagnostic] = field(default_factory=lambda: [])

    @cached_property
    def value(self) -> dict[str, Any]:
        """降维后的纯 Python dict（惰性，由 emit 层负责；尽力而为）。"""
        return reduce_object(self.document.root)

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.diagnostics)

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.WARNING]


def _compile(file: File, options: CompileOptions) -> CompilationResult:
    """统一编译核心：File + CompileOptions → CompilationResult。"""
    text = file.read()
    # 空源码 → 空配置
    if not text.strip():
        return CompilationResult(document=StdDocument())

    doc, front_diagnostics = parse_source(file)

    sandbox_impl = Sandbox(
        config=options.effective_sandbox(),
        base_dir=file.root_path,
    )
    import_resolver = ImportResolver(sandbox=sandbox_impl)
    resolver = TemplateGraphResolver(
        registry=options.registry,
        import_resolver=import_resolver,
        schema=options.schema,
    )
    analyzer = AstBuilder(resolver=resolver)
    try:
        document = analyzer.analyze(doc, file)
    except SandboxError as e:
        # 沙盒/schema 违规 → 统一为 ERROR 诊断，返回空文档（不抛出）
        return CompilationResult(
            document=StdDocument(),
            diagnostics=[Diagnostic(Severity.ERROR, e.code, dict(e.params), e.source)],
        )

    diagnostics = sorted(
        [*front_diagnostics, *document.diagnostics],
        key=lambda d: d.sort_key(),
    )
    return CompilationResult(
        document=document,
        diagnostics=diagnostics,
    )


def load(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    sandbox: SandboxConfig | None = None,
    registry: ConstraintRegistry | None = None,
    schema: Schema | None = None,
) -> CompilationResult:
    """加载 .infd/.inft 文件并编译。

    Args:
        path: 文件路径（相对导入以此为基准）
        其余选项（env/sandbox/registry/schema）见 :class:`CompileOptions`

    沙盒/schema 违规不抛出：由编译核心转为 ERROR 诊断，返回空文档。
    """
    return _compile(
        DiskFile.from_fullpath(path),
        CompileOptions(env=env, sandbox=sandbox, registry=registry, schema=schema),
    )


def compile_source(
    source: str,
    *,
    file_path: str = 'unknown',
    env: Mapping[str, str] | None = None,
    sandbox: SandboxConfig | None = None,
    registry: ConstraintRegistry | None = None,
    schema: Schema | None = None,
) -> CompilationResult:
    """编译源码字符串，返回 CompilationResult（选项见 :class:`CompileOptions`）。"""
    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=source)
    return _compile(
        file,
        CompileOptions(env=env, sandbox=sandbox, registry=registry, schema=schema),
    )


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
    return _compile(
        DiskFile.from_fullpath(path),
        CompileOptions(sandbox=SandboxConfig.deny_all(), registry=registry, schema=schema),
    )


def check(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    sandbox: SandboxConfig | None = None,
    registry: ConstraintRegistry | None = None,
    schema: Schema | None = None,
) -> list[Diagnostic]:
    """仅校验，不输出。沙盒/schema 违规已由编译核心转为 ERROR 诊断。"""
    return load(path, env=env, sandbox=sandbox, registry=registry, schema=schema).diagnostics


def compile_document(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    sandbox: SandboxConfig | None = None,
    registry: ConstraintRegistry | None = None,
    schema: Schema | None = None,
) -> StdDocument:
    """编译为 StdDocument（不经过降维），含 .root 与 .diagnostics。

    沙盒/schema 违规时返回空文档（诊断见 :meth:`load` 结果）。
    """
    result = load(path, env=env, sandbox=sandbox, registry=registry, schema=schema)
    return result.document