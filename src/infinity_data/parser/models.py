"""语法分析阶段 AST 节点（RawAst）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from infinity_data.tokenizer.models.raw_tokens import SourceRange
from infinity_data.tokenizer.models.tokens import (
    BoolToken,
    FloatToken,
    IntegerToken,
    NoexistToken,
    NullToken,
    StringToken,
)


# ═══════════════════════════════════════════════════════════
# 节点
# ═══════════════════════════════════════════════════════════
@dataclass
class AstNode:
    """AST 节点基类。"""

    source: SourceRange


# ═══════════════════════════════════════════════════════════
# 文档
# ═══════════════════════════════════════════════════════════


@dataclass
class Document(AstNode):
    """顶层文档，包含一组语句。

    顶层是隐式 dict；``: <constraint, ...>`` 以 :class:`ConstraintStmt`
    形式出现在 statements 中，语义分析阶段作用于编译产物 root。
    """

    statements: list[Statement] = field(default_factory=lambda: [])


# ═══════════════════════════════════════════════════════════
# 语句
# ═══════════════════════════════════════════════════════════


@dataclass
class TemplateImportItem(AstNode):
    """模板导入项: Name [as Alias]。"""

    name: str  # 被导入文件中的模板名
    alias: str | None = None  # 本地别名（可选）


@dataclass
class TemplateImportStmt(AstNode):
    """模板导入: !from "path" import Name1, Name2 as N2"""

    from_path: str  # 文件路径（unix 风格）
    items: list[TemplateImportItem]  # 导入项列表


@dataclass
class EnvImportStmt(AstNode):
    """环境变量导入: !env import NAME [as NEW_NAME]"""

    name: str  # 环境变量名
    alias: str | None  # 别名（可选）


@dataclass
class JsonPathKey(AstNode):
    """JSON 路径中的键访问: .key 或 .\"key\""""

    key: str


@dataclass
class JsonPathIndex(AstNode):
    """JSON 路径中的索引访问: [N]"""

    index: int


type JsonPathSegment = JsonPathKey | JsonPathIndex


@dataclass
class FileImportItem(AstNode):
    """配置文件导入项。"""

    json_path: list[JsonPathSegment]  # 路径段列表；空列表 = 导入整个文件
    alias: str  # 别名（必须）


@dataclass
class FileImportStmt(AstNode):
    """配置文件导入: !file "path" as <format> import .path.to.key as alias, ..."""

    file_path: str  # 文件路径
    format: str | None  # 文件格式: "yaml", "json", "toml" 或 None（自动检测后缀）
    imports: list[FileImportItem]


@dataclass
class TemplateField(AstNode):
    """模板内部字段定义。与普通 Field 不同之处：
    - 必须带有类型约束
    - 默认值可选（省略表示必填字段）
    - 必填字段必须在非必填字段之前
    """

    name: str
    constraints: Constraints  # 模板字段必须有类型标注
    default_value: Value | None  # None = 必填字段


@dataclass
class TemplateConfig:
    """模板头部配置（``~X(key=value)``），语法层解析为类型化字段。

    - ``allow_extra``：校验时是否放行额外字段（模板即约束 / schema）
    - ``positional``：是否允许位置参数（false = 只接受命名参数）
    - ``description``：模板文档（元数据，暂不消费，供 LSP/文档）

    未来新增配置项：在此加字段，parser 侧在对应键集合补一行（字段即白名单）。
    """

    allow_extra: bool = False
    positional: bool = True
    description: str | None = None


@dataclass
class TemplateDef(AstNode):
    """模板定义: ~Name { ... } 或 ~Name(config=value) { ... }"""

    name: str
    fields: list[TemplateField]
    config: TemplateConfig = field(default_factory=TemplateConfig)
    constraints: list[Constraint] = field(default_factory=lambda: [])


@dataclass
class Field(AstNode):
    """普通字段定义：name[: type] [= value]。

    值缺失（裸 key）不是合法语法：语义分析阶段报错。
    noexist 需显式书写 ``= noexist`` 字面量。
    """

    name: str
    constraints: Constraints | None = None
    value: Value | None = None


@dataclass
class ConstraintStmt(AstNode):
    """顶层结构级约束: ``: <constraint, ...>``（作用于编译产物 root）。

    顶层是隐式 dict，``:`` 起始的语句约束整个 root，而非某个字段。
    约束函数与字段级约束共用同一注册表。
    """

    constraints: list[Constraint]


# ═══════════════════════════════════════════════════════════
# 约束
# ═══════════════════════════════════════════════════════════


@dataclass
class ConstraintIdent(AstNode):
    """简单约束标识符，如 int, str, ?"""

    name: str


@dataclass
class ConstraintCall(AstNode):
    """约束函数调用，如 each(str)、range(1, 10)、not(?)、any(int, str)。"""

    name: str
    arguments: list[Constraint] = field(default_factory=lambda: [])


@dataclass
class ConstraintLiteral(AstNode):
    """约束中的字面量参数，如 range(1, 10) 中的 1、10。"""

    value: LiteralValue


type Constraint = ConstraintIdent | ConstraintCall | ConstraintLiteral | ErrorConstraint


@dataclass
class Constraints(AstNode):
    """约束列表，如 int, str?, <int, range(1,10)>, <int, each(str)>。

    语义说明：
    - constraints 列表，若 len > 1，隐含 all(constraint1, constraint2, ...)
    """

    constraints: list[Constraint] = field(default_factory=lambda: [])


# ═══════════════════════════════════════════════════════════
# 值
# ═══════════════════════════════════════════════════════════


@dataclass
class LiteralValue(AstNode):
    """字面量值"""

    value: FloatToken | IntegerToken | BoolToken | NullToken | NoexistToken | StringToken


@dataclass
class DollarValue(AstNode):
    """$ 导入空间引用: $NAME [as type]。

    用于引用 !env import 导入的变量。
    """

    name: str  # 变量名
    type_cast: Literal['int', 'float', 'bool', 'str', None]  # 可选类型转换


@dataclass
class DictValue(AstNode):
    """对象值: { ... }

    ``: <constraint, ...>`` 结构级约束作用于该字面量 dict 的整体。
    """

    fields: list[Field]
    constraints: list[Constraint] = field(default_factory=lambda: [])


@dataclass
class ArrayValue(AstNode):
    """数组值: [ ... ]"""

    elements: list[Value]


@dataclass
class TemplateCallValue(AstNode):
    """模板调用: Name(args...)"""

    template_name: str
    positional_args: list[Value]
    named_args: dict[str, Value]


# ═══════════════════════════════════════════════════════════
# 错误节点
# ═══════════════════════════════════════════════════════════


@dataclass
class ErrorStatement(AstNode):
    """解析失败的语句。用于错误恢复。"""

    message: str


@dataclass
class ErrorValue(AstNode):
    """解析失败的值。用于错误恢复。"""

    message: str


@dataclass
class ErrorConstraint(AstNode):
    """解析失败的约束。用于错误恢复。"""

    message: str


# ═══════════════════════════════════════════════════════════
# 联合类型
# ═══════════════════════════════════════════════════════════

type Statement = (
    TemplateImportStmt | EnvImportStmt | FileImportStmt | TemplateDef | Field | ConstraintStmt | ErrorStatement
)
type Value = LiteralValue | DollarValue | DictValue | ArrayValue | TemplateCallValue | ErrorValue
