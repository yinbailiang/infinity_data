"""语义分析器：RawAst → StdAst。

执行顺序（对应 neo_desg.md）：

1. 收集模板定义（重复定义错误、必填字段排序校验）
2. 解析模板导入（``!from``，沙盒授权 + 递归加载外部 .inft/.infd 模板）
3. 解析数据导入（``!env`` / ``!file``）
4. 模板名注册为同名校验器（**模板即约束**）
5. 逐语句分析：模板展开、约束语法糖展开、约束链执行
6. 顶层结构级约束校验（``: <...>``，作用于编译产物 root）
7. 顶层 schema 校验（strict/lenient/strip）

模板身份与可见性模型：
- 模板真名 :class:`TemplateKey`（来源文件内容 hash + 本地名），全局唯一
- 每个文件一张可见名表 scope（可见名 → 真名）；``!from ... import A as S``
  只把 ``S`` 映射进导入方 scope，原名不可见
- 名字解析（模板调用、约束里的模板名）在解析点经 scope 翻译成真名
"""

from __future__ import annotations

import decimal
from pathlib import Path
from typing import Any, cast

from infinity_data.infra.file import File
from infinity_data.parser.errors import ParseErrorCollector
from infinity_data.parser.models import (
    ArrayValue,
    Constraint,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Constraints,
    ConstraintStmt,
    DictValue,
    Document,
    DollarValue,
    EnvImportStmt,
    ErrorConstraint,
    ErrorValue,
    Field,
    FileImportStmt,
    LiteralValue,
    TemplateCallValue,
    TemplateDef,
    TemplateImportStmt,
    Value,
)
from infinity_data.parser.parser import Parser
from infinity_data.sandbox import Schema, SchemaError
from infinity_data.semantic.imports import ImportResolver
from infinity_data.semantic.models import (
    Diagnostic,
    Severity,
    StdArray,
    StdDocument,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
    TemplateKey,
)
from infinity_data.semantic.registry import (
    ConstraintFn,
    ConstraintRegistry,
    ConstraintResult,
    ResolvedConstraint,
    describe,
    fail_result,
    ok_result,
)
from infinity_data.tokenizer.errors import TokenizeErrorCollector
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.models.raw_tokens import SourceRange
from infinity_data.tokenizer.models.tokens import (
    BoolToken,
    FloatToken,
    IntegerToken,
    MultilineStringToken,
    NoexistToken,
    NullToken,
    StringToken,
)
from infinity_data.tokenizer.tokenizer import RawTokenizer

MAX_NESTING_DEPTH = 200
"""值嵌套深度上限，防止递归下降导致 RecursionError。"""

MAX_IMPORT_DEPTH = 32
"""模板导入递归深度上限（防止循环导入无限递归）。"""

_INVALID_CONSTRAINT = '@invalid'

Scope = dict[str, TemplateKey]
"""文件级可见名表：可见名 → 模板真名。"""


class SemanticAnalyzer:
    """语义分析器：将 RawAst 转换为 StandardAst。"""

    def __init__(
        self,
        *,
        registry: ConstraintRegistry | None = None,
        import_resolver: ImportResolver | None = None,
        schema: Schema | None = None,
    ) -> None:
        self._registry = registry or ConstraintRegistry()
        self._imports = import_resolver or ImportResolver()
        self._schema = schema
        self._templates: dict[TemplateKey, TemplateDef] = {}
        self._template_scopes: dict[TemplateKey, Scope] = {}
        self._template_files: dict[TemplateKey, str] = {}  # key → 来源文件 identity（同真名异文件保护）
        self._scopes_by_file: dict[str, Scope] = {}  # 文件 identity → 已构建 scope（循环导入防护）
        self._root_file: File | None = None
        self._root_scope: Scope = {}
        self._root_local_names: set[str] = set()
        self._schema_scope: Scope | None = None
        self._namespace: dict[str, Any] = {}  # $ 引用解析目标
        self._diagnostics: list[Diagnostic] = []
        self._depth = 0

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    def analyze(self, doc: Document, file: File) -> StdDocument:
        """主入口：分析 RawAst，返回 StandardAst。

        Args:
            doc: 语法分析产物
            file: 源码来源（诊断名 / 相对导入基准 / 内容 hash 均由它提供）
        """
        self._templates = {}
        self._template_scopes = {}
        self._template_files = {}
        self._scopes_by_file = {}
        self._root_file = file
        self._root_scope = {}
        self._root_local_names = set()
        self._schema_scope = None
        self._namespace = {}
        self._diagnostics = []
        self._depth = 0

        # 第一遍：收集本地模板定义（key 键控）
        self._collect_templates(doc, file.content_hash())

        # 解析模板导入（!from，含 schema.from_file 隐式导入）→ 构建主文件 scope
        self._root_scope = self._load_imported_templates(doc)

        # 解析数据导入语句（!env / !file）
        self._namespace = self._imports.resolve(doc, self._report)

        # 模板名注册为约束（模板即约束，注册表键为真名字符串）
        for key, tpl in self._templates.items():
            self._registry.register(
                str(key),
                self._make_template_constraint(key, tpl),
                description=f'模板 {key.name} 结构约束',
            )

        # 第二遍：分析语句
        root_fields: list[StdField] = []
        root_constraints: list[Constraint] = []
        for stmt in doc.statements:
            match stmt:
                case TemplateDef() | TemplateImportStmt() | EnvImportStmt() | FileImportStmt():
                    continue  # 模板定义与导入不产生输出
                case Field():
                    f = self._analyze_field(stmt, path=stmt.name, scope=self._root_scope)
                    if f is not None:
                        root_fields.append(f)
                case ConstraintStmt(constraints=cs):
                    root_constraints.extend(cs)
                case _:
                    pass  # ErrorStatement 已在语法阶段诊断

        root = StdObject(fields=root_fields)

        # 顶层结构级约束（作用于编译产物 root）
        for c in root_constraints:
            result = self._execute_spec(self._resolve_constraint(c, self._root_scope), root, c.source, '')
            if not result.ok:
                self._diagnostics.extend(result.diagnostics)

        # 顶层 schema 约束（strict/lenient/strip）
        if self._schema is not None:
            root = self._apply_schema(root)

        diagnostics = sorted(self._diagnostics, key=lambda d: d.sort_key())
        return StdDocument(root=root, diagnostics=diagnostics)

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
            self._diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f'模板 {name!r} 与内置约束同名，禁止定义（避免遮蔽 {name} 约束）',
                    source,
                )
            )
            return True
        return False

    def _check_required_order(self, stmt: TemplateDef) -> None:
        """模板内部校验：必填字段必须全部在可选字段之前。"""
        seen_optional = False
        for tf in stmt.fields:
            if tf.default_value is None:
                if seen_optional:
                    self._diagnostics.append(
                        Diagnostic(
                            Severity.ERROR,
                            f'模板 {stmt.name!r} 中必填字段 {tf.name!r} 出现在可选字段之后',
                            tf.source,
                        )
                    )
            else:
                seen_optional = True

    def _collect_templates(self, doc: Document, root_hash: str) -> None:
        for stmt in doc.statements:
            if not isinstance(stmt, TemplateDef):
                continue
            rejected = self._check_template_name_conflict(stmt.name, stmt.source)
            key = TemplateKey(content_hash=root_hash, name=stmt.name)
            if not rejected and key in self._templates:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f'模板 {stmt.name!r} 重复定义（同一文件内不允许同名模板），后者被拒绝',
                        stmt.source,
                    )
                )
                rejected = True
            # 无论是否被拒绝都校验内部（一次暴露所有错误，避免多轮修复）
            self._check_required_order(stmt)
            if rejected:
                continue  # 保留首次定义，拒绝隐式的"后者覆盖前者"
            self._templates[key] = stmt
            assert self._root_file is not None
            self._template_files[key] = self._root_file.identity
            self._root_local_names.add(stmt.name)

    # ═══════════════════════════════════════════════════════
    # 模板导入（!from）
    # ═══════════════════════════════════════════════════════

    def _load_imported_templates(self, doc: Document) -> Scope:
        """构建主文件 scope（含 schema.from_file 隐式导入）。"""
        assert self._root_file is not None
        root_id = self._root_file.identity
        loaded: set[str] = set()
        root_scope: Scope = {
            tpl.name: key for key, tpl in self._templates.items() if self._template_files.get(key) == root_id
        }

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
            for item in stmt.items:
                dep_key = dep_scope.get(item.name)
                if dep_key is None:
                    self._diagnostics.append(
                        Diagnostic(
                            Severity.ERROR,
                            f'导入文件中不存在模板 {item.name!r}',
                            item.source,
                        )
                    )
                    continue
                visible = item.alias or item.name
                if visible in root_scope:
                    if visible in self._root_local_names:
                        self._diagnostics.append(
                            Diagnostic(
                                Severity.ERROR,
                                f'导入的模板 {visible!r} 与文件内定义冲突',
                                item.source,
                            )
                        )
                    else:
                        self._diagnostics.append(
                            Diagnostic(
                                Severity.ERROR,
                                f'可见名 {visible!r} 重复导入（同一 scope 内不允许重复可见名），后者被拒绝',
                                item.source,
                            )
                        )
                else:
                    root_scope[visible] = dep_key

        # 主文件本地模板的 scope 登记（模板展开/约束校验按此解析名字）
        for key in self._templates:
            if self._template_files.get(key) == root_id:
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
            self._diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f'模板导入嵌套深度超过上限 {MAX_IMPORT_DEPTH}: {from_path}',
                    source,
                )
            )
            return {}

        file = self._imports.resolve_template_path(
            from_path,
            base_dir=base_dir,
            source=source,
            report=self._report,
        )
        if file is None:
            return {}

        file_id = file.identity
        if file_id in loaded:
            # 循环导入：返回已构建的本地名部分（本地模板先注册）
            return self._scopes_by_file.get(file_id, {})
        loaded.add(file_id)

        try:
            content_hash = file.content_hash()
        except OSError as e:
            self._diagnostics.append(Diagnostic(Severity.ERROR, f'读取模板文件失败 {file.name}: {e}', source))
            return {}

        imported_doc = self._parse_document(file)

        # 1) 本地模板：先注册（循环导入时依赖文件的本地名部分已可见）
        scope: Scope = {}
        local_names: set[str] = set()
        for s in imported_doc.statements:
            if not isinstance(s, TemplateDef):
                continue
            if self._check_template_name_conflict(s.name, s.source):
                continue
            key = TemplateKey(content_hash=content_hash, name=s.name)
            existing_file = self._template_files.get(key)
            if existing_file is not None and existing_file != file_id:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f'模板 {s.name!r} 内容与 {existing_file} 中的定义相同，'
                        '但来源文件不同，其导入依赖上下文可能不同',
                        s.source,
                    )
                )
                continue
            self._templates[key] = s
            self._template_files[key] = file_id
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
            for item in s.items:
                dep_key = dep_scope.get(item.name)
                if dep_key is None:
                    self._diagnostics.append(
                        Diagnostic(
                            Severity.ERROR,
                            f'导入文件中不存在模板 {item.name!r}',
                            item.source,
                        )
                    )
                    continue
                visible = item.alias or item.name
                if visible in scope:
                    if visible in local_names:
                        self._diagnostics.append(
                            Diagnostic(
                                Severity.ERROR,
                                f'导入的模板 {visible!r} 与文件内定义冲突',
                                item.source,
                            )
                        )
                    else:
                        self._diagnostics.append(
                            Diagnostic(
                                Severity.ERROR,
                                f'可见名 {visible!r} 重复导入（同一 scope 内不允许重复可见名），后者被拒绝',
                                item.source,
                            )
                        )
                else:
                    scope[visible] = dep_key

        # 3) 非模板语句校验 + 模板 scope 登记
        for s in imported_doc.statements:
            match s:
                case TemplateDef():
                    key = TemplateKey(content_hash=content_hash, name=s.name)
                    if key in self._templates:  # 同名冲突被拒绝的模板不登记 scope
                        self._template_scopes[key] = scope
                case TemplateImportStmt():
                    pass
                case _:
                    if file.name.endswith('.inft'):
                        self._diagnostics.append(
                            Diagnostic(
                                Severity.ERROR,
                                '.inft 文件只允许模板定义，发现其他语句',
                                s.source,
                            )
                        )

        return scope

    def _parse_document(self, file: File) -> Document:
        """词法 + 语法分析一段源码（用于外部模板文件），诊断并入当前分析。"""
        tokenize_collector = TokenizeErrorCollector()
        parse_collector = ParseErrorCollector()
        raw_tokens = RawTokenizer(
            file=file,
            error_collector=tokenize_collector,
        )
        tokens = FinalTokenizer(raw_tokens)
        parser = Parser(tokens, error_collector=parse_collector)
        doc = parser.parse()
        for err in tokenize_collector:
            self._diagnostics.append(Diagnostic.from_error(err))
        for err in parse_collector:
            self._diagnostics.append(Diagnostic.from_error(err))
        return doc

    # ═══════════════════════════════════════════════════════
    # 顶层 schema 约束
    # ═══════════════════════════════════════════════════════

    def _apply_schema(self, root: StdObject) -> StdObject:
        """对顶层对象执行 schema 模板约束（strict/lenient/strip）。"""
        assert self._schema is not None
        schema_scope = self._schema_scope
        scope = schema_scope if self._schema.from_file and schema_scope is not None else self._root_scope
        key = scope.get(self._schema.template)
        if key is None:
            raise SchemaError(f'未定义的 schema 模板 {self._schema.template!r}')
        tpl = self._templates[key]
        return self._check_schema_object(root, tpl, self._schema.mode, self._template_scopes[key])

    def _check_schema_object(self, obj: StdObject, tpl: TemplateDef, mode: str, scope: Scope) -> StdObject:
        """按模板校验顶层对象。失败抛 :class:`SchemaError`（strip 先过滤再校验）。"""
        declared = {tf.name for tf in tpl.fields}
        diags: list[Diagnostic] = []

        # 额外字段处理（模式差异）
        extra_names = [f.name for f in obj.fields if f.name not in declared]
        if extra_names:
            if mode == 'strict':
                diags.append(
                    Diagnostic(
                        Severity.ERROR,
                        f'顶层 schema 不允许额外字段: {extra_names}',
                        None,
                    )
                )
            elif mode == 'lenient':
                self._diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        f'顶层 schema 存在额外字段（已保留）: {extra_names}',
                        None,
                    )
                )
            else:  # strip
                obj = StdObject(fields=[f for f in obj.fields if f.name in declared])

        # 必填字段缺失 → 报错
        for tf in tpl.fields:
            if tf.default_value is None and obj.get(tf.name) is None:
                diags.append(
                    Diagnostic(
                        Severity.ERROR,
                        f'顶层 schema 缺少必填字段 {tf.name!r}（模板 {tpl.name}）',
                        None,
                        tf.name,
                    )
                )

        # 字段约束校验
        for tf in tpl.fields:
            f = obj.get(tf.name)
            if f is not None and f.value is not None:
                result = self._execute_constraints(tf.constraints, f.value, tf.source, tf.name, scope)
                if not result.ok:
                    diags.extend(result.diagnostics)

        # 模板级约束
        for c in tpl.constraints:
            result = self._execute_spec(self._resolve_constraint(c, scope), obj, None, '')
            if not result.ok:
                diags.extend(result.diagnostics)

        if diags:
            raise SchemaError('顶层 schema 校验失败: ' + '；'.join(d.message for d in diags))
        return obj

    # ═══════════════════════════════════════════════════════
    # 模板即约束
    # ═══════════════════════════════════════════════════════

    def _make_template_constraint(self, key: TemplateKey, tpl: TemplateDef) -> ConstraintFn:
        """生成把模板当约束用的校验函数（校验手写 dict）。

        闭包捕获：模板 key（显示名用 key.name）、定义、allow_extra、声明字段集、
        以及模板所在文件的 scope（约束里的模板名按定义点可见性解析）。
        """
        allow_extra = self._resolve_config_bool(tpl, 'allow_extra')
        declared = {tf.name for tf in tpl.fields}
        display = key.name
        scope = self._template_scopes[key]

        def check(
            value: StdValue | None,
            source: SourceRange | None,
            path: str,
            args: list[Any],
            executor: Any,
        ) -> ConstraintResult:
            if value is None:
                return fail_result(f'{path}: 期望 {display}（模板约束），实际没有值', source, path)
            if isinstance(value, StdLiteral):
                if value.kind == 'null':
                    return fail_result(
                        f'{path}: 期望 {display}，实际 null（使用 {display}? 允许可空）',
                        source,
                        path,
                    )
                return fail_result(f'{path}: 期望 {display}（对象），实际 {describe(value)}', source, path)
            if not isinstance(value, StdObject):
                return fail_result(f'{path}: 期望 {display}（对象），实际 {describe(value)}', source, path)

            diags: list[Diagnostic] = []
            field_map = {f.name: f for f in value.fields}

            # 逐字段校验
            for tf in tpl.fields:
                child = f'{path}.{tf.name}' if path else tf.name
                f = field_map.get(tf.name)
                if f is None:
                    if tf.default_value is None:
                        diags.append(
                            Diagnostic(
                                Severity.ERROR,
                                f'{child}: 模板 {display} 的必填字段 {tf.name!r} 缺失',
                                source,
                                child,
                            )
                        )
                    continue
                if f.value is not None:
                    result = self._execute_constraints(tf.constraints, f.value, tf.source, child, scope)
                    if not result.ok:
                        diags.extend(result.diagnostics)

            # 严格模式：不允许额外字段（allow_extra=true 时放行）
            if not allow_extra:
                for f in value.fields:
                    if f.name not in declared:
                        child = f'{path}.{f.name}' if path else f.name
                        diags.append(
                            Diagnostic(
                                Severity.ERROR,
                                f'{child}: 模板 {display} 不允许额外字段 {f.name!r}',
                                f.source or source,
                                child,
                            )
                        )

            # 模板级约束
            for c in tpl.constraints:
                result = self._execute_spec(self._resolve_constraint(c, scope), value, source, path)
                if not result.ok:
                    diags.extend(result.diagnostics)

            if diags:
                return ConstraintResult(ok=False, diagnostics=diags)
            return ok_result()

        return check

    def _resolve_config_bool(self, tpl: TemplateDef, key: str) -> bool:
        """读取模板配置中的布尔项（如 allow_extra）。"""
        raw = tpl.config.get(key)
        match raw:
            case LiteralValue(value=BoolToken(value=b)):
                return b
            case _:
                return False

    # ═══════════════════════════════════════════════════════
    # 约束语法糖展开
    # ═══════════════════════════════════════════════════════

    def _expand_annotation(self, annotation: Constraints) -> Constraints:
        """展开约束语法糖：多约束 ``<a, b, c>`` → ``all(a, b, c)``。

        （``type?`` → ``one(type, ?)`` 已在 parser 阶段展开。）
        """
        if len(annotation.constraints) > 1:
            return Constraints(
                source=annotation.source,
                constraints=[
                    ConstraintCall(
                        source=annotation.source,
                        name='all',
                        arguments=list(annotation.constraints),
                    ),
                ],
            )
        return annotation

    # ═══════════════════════════════════════════════════════
    # 字段分析
    # ═══════════════════════════════════════════════════════

    def _analyze_field(self, field: Field, path: str, scope: Scope) -> StdField | None:
        """分析单个字段，返回 StdField。"""
        # 1. 解析值
        value = self._resolve_value(field.value, path, scope)

        # 2. 值缺失：设计文档未定义「裸 key」，noexist 需显式字面量
        if value is None:
            self._diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f'{path}: 字段缺少值（如需 noexist 请显式书写 = noexist）',
                    field.source,
                )
            )
            return StdField(name=field.name, value=None, source=field.source)

        # 3. 约束执行
        if field.constraints is not None:
            result = self._execute_constraints(field.constraints, value, field.source, path, scope)
            if not result.ok:
                self._diagnostics.extend(result.diagnostics)
            if result.coerced_value is not None:
                value = result.coerced_value

        return StdField(name=field.name, value=value, source=field.source)

    # ═══════════════════════════════════════════════════════
    # 值解析
    # ═══════════════════════════════════════════════════════

    def _resolve_value(self, raw: Value | None, path: str, scope: Scope) -> StdValue | None:
        """将 RawAst Value 转换为 StdValue。"""
        if raw is None:
            return None

        self._depth += 1
        try:
            if self._depth > MAX_NESTING_DEPTH:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f'{path}: 嵌套层级超过上限 {MAX_NESTING_DEPTH}',
                        raw.source,
                    )
                )
                return None

            match raw:
                case LiteralValue(value=tok):
                    return self._convert_literal(tok)
                case DollarValue(name=n, type_cast=tc):
                    return self._resolve_dollar(n, tc, path)
                case DictValue(fields=fs, constraints=cs):
                    std_fields: list[StdField] = []
                    for f in fs:
                        child = f'{path}.{f.name}' if path else f.name
                        sf = self._analyze_field(f, path=child, scope=scope)
                        if sf is not None:
                            std_fields.append(sf)
                    obj = StdObject(fields=std_fields)
                    # dict 结构级约束（作用于该字面量整体）
                    for c in cs:
                        result = self._execute_spec(self._resolve_constraint(c, scope), obj, c.source, path)
                        if not result.ok:
                            self._diagnostics.extend(result.diagnostics)
                    return obj
                case ArrayValue(elements=els):
                    std_elements: list[StdValue] = []
                    for i, e in enumerate(els):
                        rv = self._resolve_value(e, f'{path}[{i}]', scope)
                        if rv is not None:
                            std_elements.append(rv)
                    return StdArray(elements=std_elements)
                case TemplateCallValue(
                    template_name=tn,
                    positional_args=pa,
                    named_args=na,
                ):
                    return self._expand_template_call(tn, pa, na, path, raw.source, scope)
                case ErrorValue(message=m):
                    self._diagnostics.append(Diagnostic(Severity.ERROR, f'{path}: {m}', raw.source))
                    return None
            return None
        finally:
            self._depth -= 1

    def _convert_literal(
        self,
        tok: StringToken | IntegerToken | FloatToken | BoolToken | NullToken | NoexistToken,
    ) -> StdLiteral:
        """将字面量 Token 转为 StdLiteral。"""
        match tok:
            case MultilineStringToken(value=v):
                return StdLiteral(kind='str', value=v)
            case StringToken(value=v):
                return StdLiteral(kind='str', value=v)
            case IntegerToken(value=v):
                return StdLiteral(kind='int', value=v)
            case FloatToken(value=v):
                return StdLiteral(kind='float', value=v)  # Decimal，含 NaN/±Inf
            case BoolToken(value=v):
                return StdLiteral(kind='bool', value=v)
            case NullToken():
                return StdLiteral(kind='null', value=None)
            case NoexistToken():
                return StdLiteral(kind='noexist', value=None)
        raise TypeError(f'未知字面量 token 类型: {type(tok)}')

    def _resolve_dollar(self, name: str, type_cast: str | None, path: str) -> StdValue:
        """解析 ``$name`` 引用，type_cast 为显式 as bool/int/float/str 转换。"""
        if name not in self._namespace:
            self._diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    f'{path}: 未找到导入变量 ${name}',
                )
            )
            return StdLiteral(kind='null', value=None)

        raw = self._namespace[name]
        if type_cast is None:
            return self._auto_literal(raw)

        match type_cast:
            case 'bool':
                if isinstance(raw, bool):
                    val: bool = raw
                elif isinstance(raw, str):
                    val = raw.lower() in ('true', '1')
                elif isinstance(raw, int | float):
                    val = bool(raw)
                else:
                    val = False
                return StdLiteral(kind='bool', value=val)
            case 'int':
                try:
                    return StdLiteral(kind='int', value=int(raw))
                except (ValueError, TypeError):
                    self._diagnostics.append(
                        Diagnostic(
                            Severity.WARNING,
                            f'{path}: 无法将 ${name}={raw!r} 转为 int',
                        )
                    )
                    return StdLiteral(kind='int', value=0)
            case 'float':
                try:
                    return StdLiteral(kind='float', value=decimal.Decimal(str(raw)))
                except (ValueError, TypeError, decimal.InvalidOperation):
                    self._diagnostics.append(
                        Diagnostic(
                            Severity.WARNING,
                            f'{path}: 无法将 ${name}={raw!r} 转为 float',
                        )
                    )
                    return StdLiteral(kind='float', value=decimal.Decimal(0))
            case 'str':
                return StdLiteral(kind='str', value=str(raw))
            case _:
                return self._auto_literal(raw)

    def _auto_literal(self, raw: Any) -> StdValue:
        """根据 Python 类型自动推断 StdValue（导入数据）。"""
        if raw is None:
            return StdLiteral(kind='null', value=None)
        if isinstance(raw, bool):
            return StdLiteral(kind='bool', value=raw)
        if isinstance(raw, int):
            return StdLiteral(kind='int', value=raw)
        if isinstance(raw, decimal.Decimal):
            return StdLiteral(kind='float', value=raw)
        if isinstance(raw, float):
            return StdLiteral(kind='float', value=decimal.Decimal(str(raw)))
        if isinstance(raw, str):
            return StdLiteral(kind='str', value=raw)
        if isinstance(raw, list):
            items = cast(list[Any], raw)
            return StdArray(elements=[self._auto_literal(e) for e in items])
        if isinstance(raw, dict):
            mapping = cast(dict[Any, Any], raw)
            return StdObject(fields=[StdField(name=str(k), value=self._auto_literal(v)) for k, v in mapping.items()])
        return StdLiteral(kind='str', value=str(raw))

    # ═══════════════════════════════════════════════════════
    # 模板展开
    # ═══════════════════════════════════════════════════════

    def _expand_template_call(
        self,
        template_name: str,
        positional_args: list[Value],
        named_args: dict[str, Value],
        path: str,
        source: SourceRange | None,
        scope: Scope,
    ) -> StdValue:
        """展开模板调用为 StdObject（名字经调用点 scope 翻译，展开用模板定义点 scope）。"""
        key = scope.get(template_name)
        if key is None:
            self._diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f'{path}: 未定义的模板 {template_name!r}',
                    source,
                )
            )
            return StdObject()
        template = self._templates[key]
        inner_scope = self._template_scopes[key]

        required = [tf for tf in template.fields if tf.default_value is None]

        # 参数映射：位置参数按定义顺序绑定必填字段
        param_values: dict[str, Value] = dict(named_args)
        for idx, pos_val in enumerate(positional_args):
            if idx < len(required):
                rf = required[idx]
                if rf.name in param_values:
                    self._diagnostics.append(
                        Diagnostic(
                            Severity.WARNING,
                            f'{path}: 模板 {template_name!r} 字段 {rf.name!r} 同时以位置和命名参数提供',
                            source,
                        )
                    )
                else:
                    param_values[rf.name] = pos_val
            else:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        f'{path}: 模板 {template_name!r} 只有 {len(required)} 个必填字段，'
                        f'提供了 {len(positional_args)} 个位置参数',
                        source,
                    )
                )

        # 必填字段缺失检查
        for rf in required:
            if rf.name not in param_values:
                self._diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f'{path}: 模板 {template_name!r} 的必填字段 {rf.name!r} 未提供',
                        source,
                    )
                )

        # 展开所有字段（参数覆盖 > 默认值 > 缺失）
        # 参数值按调用点 scope 解析；默认值按模板定义点 scope（inner_scope）解析
        std_fields: list[StdField] = []
        for tf in template.fields:
            child = f'{path}.{tf.name}' if path else tf.name

            if tf.name in param_values:
                v = self._resolve_value(param_values[tf.name], child, scope)
            elif tf.default_value is not None:
                v = self._resolve_value(tf.default_value, child, inner_scope)
            else:
                continue  # 必填且未提供 → 已在上面报错

            if v is not None:
                result = self._execute_constraints(tf.constraints, v, tf.source, child, inner_scope)
                if not result.ok:
                    self._diagnostics.extend(result.diagnostics)
                if result.coerced_value is not None:
                    v = result.coerced_value
            std_fields.append(StdField(name=tf.name, value=v, source=tf.source))

        obj = StdObject(fields=std_fields)

        # 模板级约束（: 起始，约束整个 dict）
        for c in template.constraints:
            result = self._execute_spec(self._resolve_constraint(c, inner_scope), obj, source, path)
            if not result.ok:
                self._diagnostics.extend(result.diagnostics)

        return obj

    # ═══════════════════════════════════════════════════════
    # 约束执行
    # ═══════════════════════════════════════════════════════

    def _execute_constraints(
        self,
        annotation: Constraints,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
        scope: Scope,
    ) -> ConstraintResult:
        """对值依次执行约束链（语法糖展开 → 逐约束执行 → 值强制转换）。"""
        expanded = self._expand_annotation(annotation)
        current = value
        for c in expanded.constraints:
            result = self._execute_spec(self._resolve_constraint(c, scope), current, source, path)
            if not result.ok:
                return result  # 一个失败即短路
            if result.coerced_value is not None:
                current = result.coerced_value
        return ConstraintResult(ok=True, coerced_value=current)

    def _execute_spec(
        self,
        spec: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult:
        """执行已解析的约束规格。

        诊断位置优先取约束自身的 source（spec.source，精确到该约束表达式），
        无约束位置时回退到外层 source（字段/注释点）。
        """
        if spec.name == _INVALID_CONSTRAINT:
            return fail_result(f'{path}: 无效的约束表达式', source, path)
        return self._registry.apply(spec, value, spec.source or source, path, self._apply_nested)

    def _apply_nested(
        self,
        constraint: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
    ) -> ConstraintResult:
        """嵌套约束执行回调（Executor 协议）。

        与 :meth:`_execute_spec` 一致：优先用嵌套约束自身的位置寻址。
        """
        return self._registry.apply(constraint, value, constraint.source or source, path, self._apply_nested)

    def _resolve_constraint(self, c: Constraint, scope: Scope) -> ResolvedConstraint:
        """解析约束 AST 为约束规格（名字经 scope 翻译为真名）。"""
        match c:
            case ConstraintIdent(name=n):
                return ResolvedConstraint(name=self._translate_name(n, scope), source=c.source)
            case ConstraintCall(name=n, arguments=args):
                return ResolvedConstraint(
                    name=self._translate_name(n, scope),
                    args=[self._resolve_constraint_arg(a, scope) for a in args],
                    source=c.source,
                )
            case ConstraintLiteral():
                return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source)
            case ErrorConstraint(message=m):
                self._diagnostics.append(Diagnostic(Severity.ERROR, m, c.source))
                return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source)
        return ResolvedConstraint(name=_INVALID_CONSTRAINT)

    def _resolve_constraint_arg(self, c: Constraint, scope: Scope) -> Any:
        """解析约束参数：嵌套约束 → ResolvedConstraint；字面量 → Python 值。"""
        match c:
            case ConstraintIdent(name=n):
                return ResolvedConstraint(name=self._translate_name(n, scope), source=c.source)
            case ConstraintCall(name=n, arguments=args):
                return ResolvedConstraint(
                    name=self._translate_name(n, scope),
                    args=[self._resolve_constraint_arg(a, scope) for a in args],
                    source=c.source,
                )
            case ConstraintLiteral(value=lit):
                return self._literal_python_value(lit)
            case ErrorConstraint(message=m):
                self._diagnostics.append(Diagnostic(Severity.ERROR, m, c.source))
                return ResolvedConstraint(name=_INVALID_CONSTRAINT, source=c.source)
        return ResolvedConstraint(name=_INVALID_CONSTRAINT)

    @staticmethod
    def _translate_name(name: str, scope: Scope) -> str:
        """可见名 → 真名字符串。未命中（如 has(field) 的裸字段名）保留原名。"""
        key = scope.get(name)
        return str(key) if key is not None else name

    @staticmethod
    def _literal_python_value(lit: LiteralValue) -> Any:
        """约束参数字面量 → Python 值。"""
        match lit.value:
            case IntegerToken(value=v):
                return v
            case FloatToken(value=v):
                return v
            case BoolToken(value=v):
                return v
            case MultilineStringToken(value=v):
                return v
            case StringToken(value=v):
                return v
            case NullToken():
                return None
            case NoexistToken():
                return None
        return None

    # ═══════════════════════════════════════════════════════
    # 诊断辅助
    # ═══════════════════════════════════════════════════════

    def _report(self, severity: Severity, message: str, source: SourceRange | None) -> None:
        self._diagnostics.append(Diagnostic(severity=severity, message=message, source=source))
