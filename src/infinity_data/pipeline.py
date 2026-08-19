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
from infinity_data.infra.diagnostics import Diagnostic, DiagnosticCollector, Severity
from infinity_data.infra.file import DiskFile, File, MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig, SandboxError, Schema, SchemaError
from infinity_data.semantic.builder import AstBuilder, StdDocument
from infinity_data.semantic.executor import ConstraintExecutor
from infinity_data.semantic.registry import ConstraintRegistry
from infinity_data.semantic.resolver import ImportResolver, TemplateGraphResolver


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

    - ``document``：:class:`StdDocument`（纯数据：root / templates / scope；诊断见 ``diagnostics``）
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


def _sorted_diagnostics(collector: DiagnosticCollector) -> list[Diagnostic]:
    """收集器快照 → 按位置排序（末端归一化，成功与异常路径共用）。"""
    return sorted(collector, key=lambda d: d.sort_key())


def _compile(file: File, options: CompileOptions) -> CompilationResult:
    """统一编译核心：File + CompileOptions → CompilationResult。

    三阶段语义流水线在此**顶层组装**（各阶段互相零耦合，仅经数据模型）：

    Phase 1（导入求解）→ :class:`ResolvedContext`
      → Phase 2a（AST 构建）→ :class:`StdDocument`
      → Phase 2b（约束执行 + schema 校验）→ 校验后的 root

    诊断：单一 :class:`DiagnosticCollector` 从词法到语义全程复用，
    末端仅做位置排序快照，无多集合事后合并。
    """
    text = file.read()
    # 空源码 → 空配置
    if not text.strip():
        return CompilationResult(document=StdDocument())

    # 单一诊断收集器：词法 → 语法 → 语义（Phase 1/2a/2b）全程复用
    collector = DiagnosticCollector()
    doc, front_diagnostics = parse_source(file)
    collector.extend(front_diagnostics)

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
    try:
        # Phase 1：导入求解（模板图 / 可见名表 / 数据命名空间）
        context = resolver.resolve(doc, file, collector)

        # Phase 2a：AST 构建（约束挂载未执行）
        std = AstBuilder().build(doc, context, collector)

        # Phase 2b：约束执行 + 顶层 schema 校验（两阶段共享同一注册表实例）
        executor = ConstraintExecutor(
            registry=resolver.registry,
            templates=std.templates,
            template_scopes=context.template_scopes,
        )
        executor.validate(std.root, collector)
        if resolver.schema is not None:
            scope = (
                context.schema_scope
                if resolver.schema.from_file and context.schema_scope is not None
                else context.root_scope
            )
            key = scope.get(resolver.schema.template)
            if key is None:
                raise SchemaError('schema.undefined_template', {'template': resolver.schema.template})
            tpl = std.templates[key]
            root = executor.apply_schema(std.root, resolver.schema, tpl, context.template_scopes[key], collector)
            std = replace(std, root=root)
    except SandboxError as e:
        # 沙盒/schema 违规 → 追加到共享收集器（保留此前已收集的诊断），返回空文档（不抛出）
        collector.add(Diagnostic(Severity.ERROR, e.code, dict(e.params), e.source))
        return CompilationResult(
            document=StdDocument(),
            diagnostics=_sorted_diagnostics(collector),
        )

    # 末端：StdDocument 纯数据（不携带诊断）；诊断全部由收集器快照承载
    document = StdDocument(
        root=std.root,
        templates=std.templates,
        scope=std.scope,
    )
    return CompilationResult(
        document=document,
        diagnostics=_sorted_diagnostics(collector),
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
    """编译为 StdDocument（不经过降维）：root / templates / scope（纯数据，不携带诊断）。

    沙盒/schema 违规时返回空文档；诊断见 :meth:`load` 结果（``CompilationResult.diagnostics``）。
    """
    result = load(path, env=env, sandbox=sandbox, registry=registry, schema=schema)
    return result.document