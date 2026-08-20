"""模板图求解器（Phase 1）：构建模板图、可见名表与数据命名空间。

将「模板导入（``!from``）、数据导入（``!env`` / ``!file``）、模板定义收集」
从语义分析中独立出来，产出不可变的 :class:`ResolvedContext` 供
Phase 2a（:class:`~infinity_data.semantic.builder.AstBuilder`）消费。

- 本层**不执行任何约束**：只解析名字、加载模板定义、构建 scope；
  模板展开 / 约束求值 / schema 校验全部留在 Phase 2。
- ``resolve()`` 幂等：同一输入产出等价上下文，不依赖调用历史；
  外部文件解析结果可经 ``parse_cache`` 跨调用复用（增量编译 / LSP）。
- 遮蔽检查只读查询注册表的内置约束名（不触发约束执行）。
- 诊断写入调用方注入的共享 :class:`DiagnosticCollector`（流水线单一收集器），
  本层不持有诊断列表、不产出诊断数据。
"""

from __future__ import annotations

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import Diagnostic, DiagnosticCollector, Severity
from infinity_data.infra.file import File
from infinity_data.parser import (
    Document,
    TemplateDef,
    TemplateImportItem,
    TemplateImportStmt,
)
from infinity_data.sandbox import Schema
from infinity_data.semantic.registry import ConstraintRegistry
from infinity_data.semantic.resolver.imports import ImportResolver
from infinity_data.semantic.resolver.models import ResolvedContext, Scope, TemplateKey
from infinity_data.tokenizer.models.raw_tokens import SourceRange

MAX_IMPORT_DEPTH = 32
"""模板导入递归深度上限（防止循环导入无限递归）。"""


class TemplateGraphResolver:
    """模板图求解器（Phase 1）：递归加载导入、构建 scope、解析数据导入。

    Args:
        registry: 约束注册表（仅用于内置约束名的遮蔽检查，不执行约束）
        import_resolver: 数据 / 模板导入路径解析（沙盒授权）
        schema: 顶层 schema（``from_file`` 隐式导入）
        parse_cache: 可选外部文件解析缓存（identity → Document）。
            传入后跨 ``resolve()`` 复用，文件不变时跳过重复词法/语法分析。
    """

    def __init__(
        self,
        *,
        registry: ConstraintRegistry | None = None,
        import_resolver: ImportResolver | None = None,
        schema: Schema | None = None,
        parse_cache: dict[str, Document] | None = None,
    ) -> None:
        self._registry = registry or ConstraintRegistry()
        self._imports = import_resolver or ImportResolver()
        self._schema = schema
        self._parse_cache = parse_cache
        # 工作状态（每次 resolve 重置）
        self._templates: dict[TemplateKey, TemplateDef] = {}
        self._template_scopes: dict[TemplateKey, Scope] = {}
        self._scopes_by_file: dict[str, Scope] = {}  # 文件 identity → 已构建 scope（循环导入防护）
        self._root_file: File | None = None
        self._root_scope: Scope = {}
        self._root_local_names: set[str] = set()
        self._schema_scope: Scope | None = None
        # 本次 resolve 的共享诊断收集器（流水线单一收集器，resolve() 注入）
        self._collector: DiagnosticCollector = DiagnosticCollector()

    def resolve(self, doc: Document, file: File, collector: DiagnosticCollector) -> ResolvedContext:
        """求解导入，返回不可变上下文（幂等：同一输入产出等价结果）。

        诊断（``import.*`` / ``template.*`` 域）写入 ``collector``。
        """
        self._reset(file, collector)

        # 收集本地模板定义（key 键控，身份含来源文件路径）
        self._collect_templates(doc, file.identity)

        # 解析模板导入（!from，含 schema.from_file 隐式导入）→ 构建主文件 scope
        root_scope = self._load_imported_templates(doc)

        # 解析数据导入语句（!env / !file）→ $ 引用命名空间
        namespace = self._imports.resolve(doc, self._collector)

        return ResolvedContext(
            templates=dict(self._templates),
            template_scopes=dict(self._template_scopes),
            root_scope=root_scope,  # 与 template_scopes 内的定义点 scope 同一对象
            schema_scope=self._schema_scope,
            namespace=dict(namespace),
        )

    @property
    def registry(self) -> ConstraintRegistry:
        """共享约束注册表（Phase 2 复用同一注册表：模板即约束注册 / 执行）。"""
        return self._registry

    @property
    def schema(self) -> Schema | None:
        """顶层 schema（Phase 2b 顶层校验复用同一实例）。"""
        return self._schema

    def _reset(self, file: File, collector: DiagnosticCollector) -> None:
        self._templates = {}
        self._template_scopes = {}
        self._scopes_by_file = {}
        self._root_file = file
        self._root_scope = {}
        self._root_local_names = set()
        self._schema_scope = None
        self._collector = collector

    # ═══════════════════════════════════════════════════════
    # 模板收集
    # ═══════════════════════════════════════════════════════

    def _check_template_name_conflict(self, name: str, source: SourceRange | None) -> bool:
        """模板名与已注册约束（内置/自定义）同名 → ERROR 并返回 True。

        模板即约束：定义 ``~int`` / ``~range`` 会遮蔽同名内置约束（``int`` 类型
        标注、``range(1, 100)`` 调用等语义被静默劫持），因此同名模板禁止定义，
        内置约束保持可用。
        """
        if name in self._registry.names:
            self._collector.add(Diagnostic(Severity.ERROR, 'template.shadows_builtin', {'template': name}, source))
            return True
        return False

    def _check_required_order(self, stmt: TemplateDef) -> None:
        """模板内部校验：必填字段必须全部在可选字段之前。

        例外：``positional=false`` 的模板不接受位置参数，字段顺序不影响绑定，
        允许必填与可选交错。
        """
        if not stmt.config.positional:
            return
        seen_optional = False
        for tf in stmt.fields:
            if tf.default_value is None:
                if seen_optional:
                    self._collector.add(
                        Diagnostic(
                            Severity.ERROR,
                            'template.required_order',
                            {'template': stmt.name, 'field': tf.name},
                            tf.source,
                        )
                    )
            else:
                seen_optional = True

    def _collect_templates(self, doc: Document, root_identity: str) -> None:
        for stmt in doc.statements:
            if not isinstance(stmt, TemplateDef):
                continue
            rejected = self._check_template_name_conflict(stmt.name, stmt.source)
            key = TemplateKey(identity=root_identity, name=stmt.name)
            if not rejected and key in self._templates:
                self._collector.add(
                    Diagnostic(Severity.ERROR, 'template.duplicate', {'template': stmt.name}, stmt.source)
                )
                rejected = True
            # 无论是否被拒绝都校验内部（一次暴露所有错误，避免多轮修复）
            self._check_required_order(stmt)
            if rejected:
                continue  # 保留首次定义，拒绝隐式的"后者覆盖前者"
            self._templates[key] = stmt
            self._root_local_names.add(stmt.name)

    # ═══════════════════════════════════════════════════════
    # 模板导入（!from）
    # ═══════════════════════════════════════════════════════

    def _map_import_items(
        self,
        items: list[TemplateImportItem],
        dep_scope: Scope,
        scope: Scope,
        local_names: set[str],
    ) -> None:
        """把 ``!from`` 的导入项映射进目标 scope；冲突一律 ERROR。

        - 导入文件中不存在该模板 → ERROR
        - 可见名与文件内定义同名 → ERROR（与文件内定义冲突）
        - 可见名已存在（重复导入）→ ERROR，保留先到者（拒绝隐式覆盖）
        """
        for item in items:
            dep_key = dep_scope.get(item.name)
            if dep_key is None:
                self._collector.add(
                    Diagnostic(Severity.ERROR, 'template.import_not_found', {'template': item.name}, item.source)
                )
                continue
            visible = item.alias or item.name
            if visible in scope:
                if visible in local_names:
                    self._collector.add(
                        Diagnostic(Severity.ERROR, 'template.import_conflict_local', {'visible': visible}, item.source)
                    )
                else:
                    self._collector.add(
                        Diagnostic(Severity.ERROR, 'template.import_duplicate', {'visible': visible}, item.source)
                    )
            else:
                scope[visible] = dep_key

    def _load_imported_templates(self, doc: Document) -> Scope:
        """构建主文件 scope（含 schema.from_file 隐式导入）。"""
        assert self._root_file is not None
        root_id = self._root_file.identity
        loaded: set[str] = set()
        root_scope: Scope = {tpl.name: key for key, tpl in self._templates.items() if key.identity == root_id}

        # schema.from_file 隐式导入：独立 scope 供顶层校验使用
        if self._schema is not None and self._schema.from_file:
            self._schema_scope = self._import_template_path(
                self._schema.from_file,
                base_dir=self._imports.base_dir,
                source=None,
                loaded=loaded,
                depth=0,
            )

        for stmt in doc.statements:
            if not isinstance(stmt, TemplateImportStmt):
                continue
            dep_scope = self._import_template_path(
                stmt.from_path,
                base_dir=self._imports.base_dir,
                source=stmt.source,
                loaded=loaded,
                depth=0,
            )
            self._map_import_items(stmt.items, dep_scope, root_scope, self._root_local_names)
        # 主文件本地模板的 scope 登记（模板展开/约束校验按此解析名字）
        for key in self._templates:
            if key.identity == root_id:
                self._template_scopes[key] = root_scope
        return root_scope

    def _import_template_path(
        self,
        from_path: str,
        *,
        base_dir: Path,
        source: SourceRange | None,
        loaded: set[str],
        depth: int,
    ) -> Scope:
        """加载单个模板文件，返回该文件的可见 scope（递归解析嵌套 !from）。"""
        if depth > MAX_IMPORT_DEPTH:
            self._collector.add(
                Diagnostic(
                    Severity.ERROR, 'template.import_depth', {'max': MAX_IMPORT_DEPTH, 'path_src': from_path}, source
                )
            )
            return {}

        file = self._imports.resolve_template_path(
            from_path,
            base_dir=base_dir,
            source=source,
            collector=self._collector,
        )
        if file is None:
            return {}

        file_id = file.identity
        if file_id in loaded:
            # 循环导入：返回已构建的本地名部分（本地模板先注册）
            return self._scopes_by_file.get(file_id, {})
        loaded.add(file_id)

        try:
            _ = file.content_hash()  # 触发内容读取；身份不含内容，仍需校验文件可读
        except OSError as e:
            self._collector.add(
                Diagnostic(Severity.ERROR, 'template.read_failed', {'file': file.name, 'error': e}, source)
            )
            return {}

        imported_doc = self._parse_document(file)

        # 1) 本地模板：先注册（循环导入时依赖文件的本地名部分已可见）
        #    身份含来源文件路径：不同路径的文件即使内容相同也是不同模板身份——
        #    模板内部 !from 按定义文件所在目录解析，内容相同的文件其依赖语义
        #    可能不同，不能互相覆盖（纯内容寻址无法表达这一区别）
        scope: Scope = {}
        local_names: set[str] = set()
        for s in imported_doc.statements:
            if not isinstance(s, TemplateDef):
                continue
            if self._check_template_name_conflict(s.name, s.source):
                continue
            key = TemplateKey(identity=file_id, name=s.name)
            self._templates[key] = s
            scope[s.name] = key
            local_names.add(s.name)
        self._scopes_by_file[file_id] = scope

        # 2) 嵌套 !from：可见名映射
        for s in imported_doc.statements:
            if not isinstance(s, TemplateImportStmt):
                continue
            dep_scope = self._import_template_path(
                s.from_path,
                base_dir=file.root_path,
                source=s.source,
                loaded=loaded,
                depth=depth + 1,
            )
            self._map_import_items(s.items, dep_scope, scope, local_names)

        # 3) 非模板语句校验 + 模板 scope 登记
        for s in imported_doc.statements:
            match s:
                case TemplateDef():
                    key = TemplateKey(identity=file_id, name=s.name)
                    if key in self._templates:  # 同名冲突被拒绝的模板不登记 scope
                        self._template_scopes[key] = scope
                case TemplateImportStmt():
                    pass
                case _:
                    if file.name.endswith('.inft'):
                        self._collector.add(Diagnostic(Severity.ERROR, 'inft.not_allowed', {}, s.source))

        return scope

    def _parse_document(self, file: File) -> Document:
        """词法 + 语法分析一段源码（用于外部模板文件）。

        启用 ``parse_cache`` 时按文件 identity 复用（文件不变跳过重复分析）。
        """
        if self._parse_cache is not None:
            cached = self._parse_cache.get(file.identity)
            if cached is not None:
                return cached
        doc, _ = parse_source(file, self._collector)
        if self._parse_cache is not None:
            self._parse_cache[file.identity] = doc
        return doc
