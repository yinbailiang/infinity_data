"""语义分析器：RawAst → StandardAst。

基于 neo_desg.md 重新设计。
执行顺序：
1. 收集模板定义
2. 展开模板调用（宏展开）
3. 解析裸 key（key → key 标记，无类型无值 → noexist 存在性标记）
4. 展开约束语法糖：<a, b, c> → all(a, b, c), type? → one(type, ?)
5. 执行约束链
6. 输出 StandardAst
"""

from __future__ import annotations

import math
from typing import Any

from infinity_data.analyzer.constraints import (
    ConstraintRegistry,
    ConstraintResult,
    apply_constraint_by_name,
    make_diagnostic,
)
from infinity_data.analyzer.models import (
    Diagnostic,
    StdArray,
    StdDocument,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.parser.models import (
    ArrayValue,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Document,
    DollarValue,
    EnvImportStmt,
    Field,
    FileImportStmt,
    LiteralValue,
    ObjectValue,
    TemplateCallValue,
    TemplateDef,
    TemplateField,
    TemplateImportStmt,
    TypeAnnotation,
    Value,
)
from infinity_data.tokenizer.models import SourceInfo


class SemanticAnalyzer:
    """语义分析器：将 RawAst 转换为 StandardAst。"""

    def __init__(self, registry: ConstraintRegistry | None = None) -> None:
        self._registry = registry or ConstraintRegistry()
        self._templates: dict[str, TemplateDef] = {}
        self._import_namespace: dict[str, Any] = {}  # $ 引用解析目标
        self._diagnostics: list[Diagnostic] = []

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    def analyze(self, doc: Document) -> StdDocument:
        """主入口：分析 RawAst，返回 StandardAst。"""
        self._diagnostics = []
        self._templates = {}
        self._import_namespace = {}

        # 第一遍：收集模板定义
        self._collect_templates(doc)

        # 解析导入语句
        self._resolve_imports(doc)

        # 将模板名注册为约束
        for name, tpl in self._templates.items():
            self._registry.register(name, self._make_template_constraint(name, tpl))

        # 第二遍：分析语句
        root_fields: list[StdField] = []
        for stmt in doc.statements:
            match stmt:
                case TemplateDef():
                    continue  # 模板定义不产生输出
                case TemplateImportStmt():
                    continue  # 导入已解析
                case EnvImportStmt():
                    continue
                case FileImportStmt():
                    continue
                case Field():
                    result = self._analyze_field(stmt, path=stmt.name)
                    if result is not None:
                        root_fields.append(result)

        return StdDocument(
            root=StdObject(fields=root_fields),
            diagnostics=self._diagnostics,
        )

    # ═══════════════════════════════════════════════════════
    # 模板收集
    # ═══════════════════════════════════════════════════════

    def _collect_templates(self, doc: Document) -> None:
        for stmt in doc.statements:
            if isinstance(stmt, TemplateDef):
                if stmt.name in self._templates:
                    self._warn(f"模板 {stmt.name!r} 重复定义，后者覆盖前者", stmt.source)
                self._templates[stmt.name] = stmt

    # ═══════════════════════════════════════════════════════
    # 导入解析
    # ═══════════════════════════════════════════════════════

    def _resolve_imports(self, doc: Document) -> None:
        """解析导入语句，填充 _import_namespace 和 _templates。"""
        for stmt in doc.statements:
            if isinstance(stmt, EnvImportStmt):
                import os
                name = stmt.alias or stmt.name
                value = os.environ.get(stmt.name, "")
                self._import_namespace[name] = value
                self._info(f"env import: ${name} = {value!r}", stmt.source)

            elif isinstance(stmt, FileImportStmt):
                self._resolve_file_import(stmt)

            elif isinstance(stmt, TemplateImportStmt):
                self._resolve_template_import(stmt)

    def _resolve_file_import(self, stmt: FileImportStmt) -> None:
        """解析 !file import 语句。"""
        import json
        import os

        # 尝试读取文件
        file_path = stmt.file_path
        if not os.path.isabs(file_path):
            # 相对路径暂不处理
            pass

        if not os.path.exists(file_path):
            self._warn(f"导入文件不存在: {file_path}", stmt.source)
            return

        # 自动检测格式
        fmt = stmt.format
        if fmt is None:
            ext = os.path.splitext(file_path)[1].lower()
            fmt_map = {".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml"}
            fmt = fmt_map.get(ext, "json")

        try:
            if fmt == "json":
                import json
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
            elif fmt in ("yaml", "yml"):
                try:
                    import yaml
                    with open(file_path, encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                except ImportError:
                    self._warn("yaml 支持需要安装 PyYAML", stmt.source)
                    return
            elif fmt == "toml":
                try:
                    import tomllib
                    with open(file_path, "rb") as f:
                        data = tomllib.load(f)
                except ImportError:
                    self._warn("toml 支持需要 Python 3.11+", stmt.source)
                    return
            else:
                self._warn(f"不支持的文件格式: {fmt}", stmt.source)
                return
        except Exception as e:
            self._err(f"读取文件失败 {file_path}: {e}", stmt.source)
            return

        # 按 JSON 路径提取数据
        for item in stmt.imports:
            alias = item.alias or item.json_path.lstrip(".")
            try:
                value = self._resolve_json_path(data, item.json_path)
                self._import_namespace[alias] = value
                self._info(f"file import: ${alias} = {value!r}", stmt.source)
            except (KeyError, IndexError, TypeError) as e:
                self._warn(f"无法解析路径 {item.json_path} 在 {file_path}: {e}", item.source)

    def _resolve_json_path(self, data: Any, path: str) -> Any:
        """按 JSON 路径解析数据。支持 .key, [index], ."key"。"""
        if path == ".":
            return data

        current = data
        # 简单路径解析
        import re
        # 匹配 .key 或 [index] 或 ."key"
        segments = re.findall(r'\.([^.["]+)|\.("(?:[^"\\]|\\.)*")|\[(\d+)\]', path)
        for seg in segments:
            key, quoted_key, index = seg
            if index:
                current = current[int(index)]
            elif quoted_key:
                k = quoted_key.strip('"')
                current = current[k]
            elif key:
                current = current[key]
        return current

    def _resolve_template_import(self, stmt: TemplateImportStmt) -> None:
        """解析 !from import（模板导入）。"""
        import os

        file_path = stmt.from_path
        if not os.path.isabs(file_path):
            self._warn(f"相对路径模板导入尚未实现: {file_path}", stmt.source)
            return

        if not os.path.exists(file_path):
            self._warn(f"模板文件不存在: {file_path}", stmt.source)
            return

        # 实际加载需要完整的解析流水线，这里做简化处理
        self._info(f"模板导入: {file_path} → {stmt.names}", stmt.source)

    # ═══════════════════════════════════════════════════════
    # 模板即约束
    # ═══════════════════════════════════════════════════════

    def _make_template_constraint(self, name: str, tpl: TemplateDef):
        """生成一个把模板当约束用的校验函数。"""
        def _check_template(
            val: StdValue | None,
            source: SourceInfo | None,
            path: str,
            args: list[Any],
        ) -> ConstraintResult:
            if val is None:
                return ConstraintResult(ok=False, diagnostics=[
                    make_diagnostic(f"{path}: 期望 {name}（模板约束），实际没有值", source, path),
                ])
            if isinstance(val, StdLiteral) and val.kind == "null":
                # null 值需要配合 nullable 处理
                return ConstraintResult(ok=False, diagnostics=[
                    make_diagnostic(f"{path}: 期望 {name}，实际 null（使用 {name}? 允许可空）", source, path),
                ])
            if not isinstance(val, StdObject):
                return ConstraintResult(ok=False, diagnostics=[
                    make_diagnostic(f"{path}: 期望 {name}（对象），实际 {type(val).__name__}", source, path),
                ])

            # 校验每个模板字段
            diags: list[Diagnostic] = []
            field_map: dict[str, StdField] = {f.name: f for f in val.fields}

            for tf in tpl.fields:
                child_path = f"{path}.{tf.name}" if path else tf.name
                if tf.name not in field_map:
                    if tf.default_value is None:
                        # 必填字段缺失
                        diags.append(make_diagnostic(
                            f"{child_path}: 模板 {name} 的必填字段 {tf.name!r} 缺失",
                            source, child_path,
                        ))
                    # 可选字段缺失 → 不影响
                    continue
                field_val = field_map[tf.name].value
                # 递归执行约束
                expanded_annotation = self._expand_annotation(tf.type_annotation)
                result = self._execute_constraints(expanded_annotation, field_val, source, child_path)
                if not result.ok:
                    diags.extend(result.diagnostics)

            # 严格模式：检查多余字段
            for f in val.fields:
                if f.name not in {tf.name for tf in tpl.fields}:
                    child_path = f"{path}.{f.name}" if path else f.name
                    diags.append(make_diagnostic(
                        f"{child_path}: 模板 {name} 不允许额外字段 {f.name!r}",
                        f.source, child_path,
                    ))

            if diags:
                return ConstraintResult(ok=False, diagnostics=diags)
            return ConstraintResult(ok=True)

        return _check_template

    # ═══════════════════════════════════════════════════════
    # 约束语法糖展开
    # ═══════════════════════════════════════════════════════

    def _expand_annotation(self, annotation: TypeAnnotation) -> TypeAnnotation:
        """展开约束语法糖：
        - nullable (type?) → one(type, ?)
        - 多约束 <a, b, c> → all(a, b, c)
        """
        constraints = list(annotation.constraints)

        if annotation.nullable:
            # type? → one(type, ?)
            constraints = [
                ConstraintCall(name="one", arguments=[
                    *constraints,
                    ConstraintIdent(name="?"),
                ])
            ]

        if len(constraints) > 1:
            # <a, b, c> → all(a, b, c)
            constraints = [
                ConstraintCall(name="all", arguments=constraints),
            ]

        return TypeAnnotation(constraints=constraints, nullable=False)

    # ═══════════════════════════════════════════════════════
    # 字段分析
    # ═══════════════════════════════════════════════════════

    def _analyze_field(self, field: Field, path: str) -> StdField | None:
        """分析单个字段，返回 StdField。"""

        # 1. 解析值
        value = self._resolve_value(field.value, path)

        # 2. 裸 key 处理：无类型无值 → noexist 存在性标记
        if field.type_annotation is None and value is None:
            value = StdLiteral(kind="noexist", value=None)

        # 3. 约束执行
        if field.type_annotation is not None and value is not None:
            expanded = self._expand_annotation(field.type_annotation)
            result = self._execute_constraints(expanded, value, field.source, path)
            if not result.ok:
                self._diagnostics.extend(result.diagnostics)
            if result.coerced_value is not None:
                value = result.coerced_value

        return StdField(name=field.name, value=value, source=field.source)

    # ═══════════════════════════════════════════════════════
    # 值解析
    # ═══════════════════════════════════════════════════════

    def _resolve_value(self, raw: Value | None, path: str) -> StdValue | None:
        """将 RawAst Value 转换为 StdValue。"""
        if raw is None:
            return None

        match raw:
            case LiteralValue(kind=k, raw=r):
                return self._convert_literal(k, r)
            case DollarValue(name=n, type_cast=tc):
                return self._resolve_dollar(n, tc, path)
            case ObjectValue(fields=fs):
                std_fields: list[StdField] = []
                for f in fs:
                    child_path = f"{path}.{f.name}" if path else f.name
                    result = self._analyze_field(f, path=child_path)
                    if result is not None:
                        std_fields.append(result)
                return StdObject(fields=std_fields)
            case ArrayValue(elements=els):
                std_elements: list[StdValue] = []
                for i, e in enumerate(els):
                    elem_path = f"{path}[{i}]"
                    resolved = self._resolve_value(e, elem_path)
                    if resolved is not None:
                        std_elements.append(resolved)
                return StdArray(elements=std_elements)
            case TemplateCallValue(template_name=tn, positional_args=pa, named_args=na, source=src):
                return self._expand_template_call(tn, pa, na, path, src)
            case _:
                self._warn(f"{path}: 未知值类型", None)
                return None

    def _convert_literal(self, kind: str, raw: str) -> StdLiteral:
        """将 RawAst 字面量转为 StdLiteral。"""
        match kind:
            case "str" | "mlstr":
                return StdLiteral(kind="str", value=raw)
            case "int":
                return StdLiteral(kind="int", value=int(raw))
            case "float":
                return StdLiteral(kind="float", value=float(raw))
            case "true":
                return StdLiteral(kind="bool", value=True)
            case "false":
                return StdLiteral(kind="bool", value=False)
            case "null":
                return StdLiteral(kind="null", value=None)
            case "noexist":
                return StdLiteral(kind="noexist", value=None)
            case "nan":
                return StdLiteral(kind="nan", value=float("nan"))
            case "+inf":
                return StdLiteral(kind="+inf", value=float("inf"))
            case "-inf":
                return StdLiteral(kind="-inf", value=float("-inf"))
            case _:
                return StdLiteral(kind=kind, value=raw)

    def _resolve_dollar(self, name: str, type_cast: str | None, path: str) -> StdValue:
        """解析 $name 引用。

        type_cast 为 None 时自动推断 Python 类型（保留原始类型）；
        显式 as bool/int/float/str 时执行强制转换。
        """
        if name not in self._import_namespace:
            self._warn(f"{path}: 未找到导入变量 ${name}", None)
            return StdLiteral(kind="null", value=None)

        raw = self._import_namespace[name]

        # 无显式类型转换 → 自动推断
        if type_cast is None:
            return self._auto_literal(raw)

        match type_cast:
            case "bool":
                if isinstance(raw, bool):
                    val = raw
                elif isinstance(raw, str):
                    val = raw.lower() in ("true", "1")
                elif isinstance(raw, (int, float)):
                    val = bool(raw)
                else:
                    val = False
                return StdLiteral(kind="bool", value=val)
            case "int":
                try:
                    return StdLiteral(kind="int", value=int(raw))
                except (ValueError, TypeError):
                    self._warn(f"{path}: 无法将 ${name}={raw!r} 转为 int", None)
                    return StdLiteral(kind="int", value=0)
            case "float":
                try:
                    return StdLiteral(kind="float", value=float(raw))
                except (ValueError, TypeError):
                    self._warn(f"{path}: 无法将 ${name}={raw!r} 转为 float", None)
                    return StdLiteral(kind="float", value=0.0)
            case "str":
                return StdLiteral(kind="str", value=str(raw))
            case _:
                return self._auto_literal(raw)

    def _auto_literal(self, raw: object) -> StdValue:
        """根据 Python 类型自动推断 StdLiteral。"""
        if isinstance(raw, bool):
            return StdLiteral(kind="bool", value=raw)
        if isinstance(raw, int):
            return StdLiteral(kind="int", value=raw)
        if isinstance(raw, float):
            return StdLiteral(kind="float", value=raw)
        if isinstance(raw, str):
            return StdLiteral(kind="str", value=raw)
        if isinstance(raw, list):
            elements = [self._auto_literal(e) for e in raw]
            return StdArray(elements=elements)
        if isinstance(raw, dict):
            fields = [
                StdField(name=str(k), value=self._auto_literal(v))
                for k, v in raw.items()
            ]
            return StdObject(fields=fields)
        if raw is None:
            return StdLiteral(kind="null", value=None)
        # fallback: stringify
        return StdLiteral(kind="str", value=str(raw))

    # ═══════════════════════════════════════════════════════
    # 模板展开
    # ═══════════════════════════════════════════════════════

    def _expand_template_call(
        self,
        template_name: str,
        positional_args: list[Value],
        named_args: dict[str, Value],
        path: str,
        source: SourceInfo | None,
    ) -> StdValue:
        """展开模板调用为 StdObject。"""
        template = self._templates.get(template_name)
        if template is None:
            self._err(f"{path}: 未定义的模板 {template_name!r}", source)
            return StdObject()

        # 区分必填和可选字段
        required_fields: list[TemplateField] = []
        optional_fields: list[TemplateField] = []
        for tf in template.fields:
            if tf.default_value is None:
                required_fields.append(tf)
            else:
                optional_fields.append(tf)

        # 参数映射
        param_values: dict[str, Value] = dict(named_args)

        # 位置参数绑定必填字段
        for idx, pos_val in enumerate(positional_args):
            if idx < len(required_fields):
                rf = required_fields[idx]
                if rf.name not in param_values:
                    param_values[rf.name] = pos_val
            else:
                self._warn(f"{path}: 模板 {template_name!r} 只有 {len(required_fields)} 个必填字段，却提供了 {len(positional_args)} 个位置参数", source)

        # 检查必填字段是否全部提供
        for rf in required_fields:
            if rf.name not in param_values:
                self._err(f"{path}: 模板 {template_name!r} 的必填字段 {rf.name!r} 未提供", source)

        # 展开所有字段
        std_fields: list[StdField] = []
        for tf in template.fields:
            child_path = f"{path}.{tf.name}" if path else tf.name

            if tf.name in param_values:
                # 参数覆盖
                override_val = self._resolve_value(param_values[tf.name], child_path)
                # 执行模板字段的约束
                if override_val is not None:
                    expanded = self._expand_annotation(tf.type_annotation)
                    result = self._execute_constraints(expanded, override_val, tf.source, child_path)
                    if not result.ok:
                        self._diagnostics.extend(result.diagnostics)
                    if result.coerced_value is not None:
                        override_val = result.coerced_value
                std_fields.append(StdField(name=tf.name, value=override_val, source=tf.source))
            elif tf.default_value is not None:
                # 使用默认值
                default_val = self._resolve_value(tf.default_value, child_path)
                if default_val is not None:
                    expanded = self._expand_annotation(tf.type_annotation)
                    result = self._execute_constraints(expanded, default_val, tf.source, child_path)
                    if not result.ok:
                        self._diagnostics.extend(result.diagnostics)
                    if result.coerced_value is not None:
                        default_val = result.coerced_value
                std_fields.append(StdField(name=tf.name, value=default_val, source=tf.source))
            else:
                # 必填但未提供 → 已在上面报错
                pass

        return StdObject(fields=std_fields)

    # ═══════════════════════════════════════════════════════
    # 约束执行
    # ═══════════════════════════════════════════════════════

    def _execute_constraints(
        self,
        annotation: TypeAnnotation,
        value: StdValue | None,
        source: SourceInfo | None,
        path: str,
    ) -> ConstraintResult:
        """对值依次执行约束链。"""
        if not annotation.constraints:
            return ConstraintResult(ok=True)

        current = value
        for constraint in annotation.constraints:
            result = self._execute_single_constraint(constraint, current, source, path)
            if not result.ok:
                return result  # 一个失败就停
            if result.coerced_value is not None:
                current = result.coerced_value

        return ConstraintResult(ok=True, coerced_value=current)

    def _execute_single_constraint(
        self,
        constraint: object,
        value: StdValue | None,
        source: SourceInfo | None,
        path: str,
    ) -> ConstraintResult:
        """执行单个约束。"""
        match constraint:
            case ConstraintIdent(name=n):
                return apply_constraint_by_name(n, value, source, path, [])
            case ConstraintCall(name=n, arguments=args):
                resolved_args = [self._resolve_constraint_arg(a) for a in args]
                return apply_constraint_by_name(n, value, source, path, resolved_args)
            case _:
                return ConstraintResult(ok=False, diagnostics=[
                    make_diagnostic(f"{path}: 未知约束类型", source, path),
                ])

    def _resolve_constraint_arg(self, arg: object) -> object:
        """解析约束参数。"""
        if isinstance(arg, ConstraintIdent):
            return arg.name
        if isinstance(arg, ConstraintLiteral):
            match arg.kind:
                case "str":
                    return arg.raw
                case "int":
                    return int(arg.raw)
                case "float":
                    return float(arg.raw)
                case "true":
                    return True
                case "false":
                    return False
                case "null":
                    return None
                case _:
                    return str(arg.raw)
        return str(arg)

    # ═══════════════════════════════════════════════════════
    # 诊断辅助
    # ═══════════════════════════════════════════════════════

    def _err(self, msg: str, source: SourceInfo | None, path: str = "") -> None:
        self._diagnostics.append(Diagnostic(level="error", message=msg, source=source, path=path))

    def _warn(self, msg: str, source: SourceInfo | None, path: str = "") -> None:
        self._diagnostics.append(Diagnostic(level="warning", message=msg, source=source, path=path))

    def _info(self, msg: str, source: SourceInfo | None, path: str = "") -> None:
        self._diagnostics.append(Diagnostic(level="info", message=msg, source=source, path=path))

