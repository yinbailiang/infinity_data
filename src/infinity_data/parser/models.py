"""语法分析阶段 AST 节点（RawAst）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from infinity_data.tokenizer.models import SourceInfo


@dataclass
class Document:
    """顶层文档，包含一组语句。"""
    statements: list[Statement] = field(default_factory=lambda:[])


# ── 语句 ────────────────────────────────────────────────


@dataclass
class ImportStmt:
    """导入语句：!from <path> import <name>, ..."""
    from_path: str
    names: list[str]
    source: SourceInfo


@dataclass
class TemplateDef:
    """模板定义：@Name { ... }"""
    name: str
    source: SourceInfo
    body: list[Statement] = field(default_factory=lambda:[])


@dataclass
class Field:
    """字段定义：name[: type] [= value]"""
    name: str
    source: SourceInfo
    type_annotation: TypeAnnotation | None = None
    value: Value | None = None


# ── 类型标注 ────────────────────────────────────────────


@dataclass
class ConstraintCall:
    """约束函数调用，如 each(str)、range(1, 10)"""
    name: str
    arguments: list[Constraint] = field(default_factory=lambda:[])


@dataclass
class ConstraintIdent:
    """简单约束标识符，如 int、str、?"""
    name: str


@dataclass
class ConstraintLiteral:
    """约束中的字面量参数，如 range(1, 10) 中的 1、10"""
    kind: str  # "int", "float", "str", "true", "false", "null"
    raw: str


type Constraint = ConstraintIdent | ConstraintCall | ConstraintLiteral


@dataclass
class TypeAnnotation:
    """类型标注，如 int, str?, <int, range(1,10)>"""
    constraints: list[Constraint] = field(default_factory=lambda:[])
    nullable: bool = False


# ── 值 ──────────────────────────────────────────────────


@dataclass
class LiteralValue:
    """字面量值。"""
    kind: str  # "str", "int", "float", "true", "false", "null", "exist"
    raw: str


@dataclass
class ObjectValue:
    """对象值 { ... }"""
    fields: list[Field] = field(default_factory=lambda:[])


@dataclass
class ArrayValue:
    """数组值 [ ... ]"""
    elements: list[Value] = field(default_factory=lambda:[])


@dataclass
class TemplateCallValue:
    """模板调用：Name(args...)"""
    template_name: str
    source: SourceInfo
    positional_args: list[Value] = field(default_factory=lambda:[])
    named_args: dict[str, Value] = field(default_factory=lambda:{})


# ── 联合类型 ────────────────────────────────────────────

type Statement = ImportStmt | TemplateDef | Field
type Value = LiteralValue | ObjectValue | ArrayValue | TemplateCallValue
