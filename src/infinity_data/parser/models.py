"""语法分析阶段 AST 节点（RawAst）。

基于 neo_desg.md 重新设计，支持：
- 三种导入语句：!from（模板导入）、!env（环境变量导入）、!file（配置文件导入）
- $ 命名空间引用及 as 类型转换
- 新的字面量类型：noexist, nan, +inf, -inf
- 多行字符串
"""

from __future__ import annotations

from dataclasses import dataclass, field

from infinity_data.tokenizer.models import SourceInfo


# ═══════════════════════════════════════════════════════════
# 文档
# ═══════════════════════════════════════════════════════════

@dataclass
class Document:
    """顶层文档，包含一组语句。"""
    statements: list[Statement] = field(default_factory=lambda: [])


# ═══════════════════════════════════════════════════════════
# 语句
# ═══════════════════════════════════════════════════════════

@dataclass
class TemplateImportStmt:
    """模板导入: !from "path" import Name1, Name2"""
    from_path: str        # 文件路径（unix 风格）
    names: list[str]      # 导入的模板名列表
    source: SourceInfo


@dataclass
class EnvImportStmt:
    """环境变量导入: !env import NAME [as NEW_NAME]"""
    name: str             # 环境变量名
    alias: str | None     # 别名（可选）
    source: SourceInfo


@dataclass
class FileImportStmt:
    """配置文件导入: !file "path" as <format> import .path.to.key [as alias], ..."""
    file_path: str        # 文件路径
    format: str | None    # 文件格式: "yaml", "json", "toml" 或 None（自动检测后缀）
    imports: list[FileImportItem] = field(default_factory=lambda: [])
    source: SourceInfo | None = None


@dataclass
class FileImportItem:
    """配置文件导入项。"""
    json_path: str        # 如 ".a.b[0].c" 或 "."
    alias: str | None     # 别名（可选）
    source: SourceInfo | None = None


@dataclass
class TemplateDef:
    """模板定义: ~Name { ... }"""
    name: str
    source: SourceInfo
    fields: list[TemplateField] = field(default_factory=lambda: [])


@dataclass
class TemplateField:
    """模板内部字段定义。与普通 Field 不同之处：
    - 必须带有类型约束
    - 默认值可选（省略表示必填字段）
    - 必填字段必须在非必填字段之前
    """
    name: str
    source: SourceInfo
    type_annotation: TypeAnnotation                 # 模板字段必须有类型标注
    default_value: Value | None = None              # None = 必填字段


@dataclass
class Field:
    """普通字段定义：name[: type] [= value]。"""
    name: str
    source: SourceInfo
    type_annotation: TypeAnnotation | None = None
    value: Value | None = None


# ═══════════════════════════════════════════════════════════
# 类型标注 / 约束
# ═══════════════════════════════════════════════════════════

@dataclass
class ConstraintIdent:
    """简单约束标识符，如 int, str, ?"""
    name: str


@dataclass
class ConstraintCall:
    """约束函数调用，如 each(str)、range(1, 10)、not(?)、any(int, str)。"""
    name: str
    arguments: list[Constraint] = field(default_factory=lambda: [])


@dataclass
class ConstraintLiteral:
    """约束中的字面量参数，如 range(1, 10) 中的 1、10。"""
    kind: str  # "int", "float", "str", "true", "false", "null"
    raw: str


type Constraint = ConstraintIdent | ConstraintCall | ConstraintLiteral


@dataclass
class TypeAnnotation:
    """类型标注，如 int, str?, <int, range(1,10)>, <int, each(str)>。

    语义说明：
    - constraints 列表，若 len > 1，隐含 all(constraint1, constraint2, ...)
    - nullable: 当标注为 type? 时为 True，等价于 one(type, ?)
    - 单约束省略尖括号: field: int = 10
    """
    constraints: list[Constraint] = field(default_factory=lambda: [])
    nullable: bool = False


# ═══════════════════════════════════════════════════════════
# 值
# ═══════════════════════════════════════════════════════════

@dataclass
class LiteralValue:
    """字面量值。

    kind 可以是:
    - "str" / "mlstr"          字符串 / 多行字符串
    - "int" / "float"          数字
    - "true" / "false"         布尔
    - "null" / "noexist"       存在性
    - "nan" / "+inf" / "-inf"  特殊浮点
    """
    kind: str
    raw: str

@dataclass
class DollarValue:
    """$ 导入空间引用: $NAME [as type]。

    用于引用 !env import 或 !file import 导入的变量。
    """
    name: str                            # 变量名
    source: SourceInfo
    type_cast: str | None = None         # as type: "bool", "int", "float", "str"


@dataclass
class ObjectValue:
    """对象值: { ... }"""
    fields: list[Field] = field(default_factory=lambda: [])


@dataclass
class ArrayValue:
    """数组值: [ ... ]"""
    elements: list[Value] = field(default_factory=lambda: [])


@dataclass
class TemplateCallValue:
    """模板调用: Name(args...)"""
    template_name: str
    source: SourceInfo
    positional_args: list[Value] = field(default_factory=lambda: [])
    named_args: dict[str, Value] = field(default_factory=lambda: {})


# ═══════════════════════════════════════════════════════════
# 联合类型
# ═══════════════════════════════════════════════════════════

type Statement = TemplateImportStmt | EnvImportStmt | FileImportStmt | TemplateDef | Field
type Value = LiteralValue | DollarValue | ObjectValue | ArrayValue | TemplateCallValue

