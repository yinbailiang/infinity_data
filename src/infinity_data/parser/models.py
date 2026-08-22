"""语法分析阶段 AST 节点（RawAst）。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
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
# 规范化序列化辅助（canonical 输出标准 infd 源码，可被 parser 还原）
# ═══════════════════════════════════════════════════════════


def _canonical_str(s: str) -> str:
    """字符串 → 标准单行 infd 字符串字面量（json 风格转义，UTF-8 保留）。"""
    return json.dumps(s, ensure_ascii=False)


def _canonical_constraint_list(constraints: Iterable['Constraint']) -> str:
    """约束列表 → infd 类型标注：单约束省略尖括号，多约束 ``<a, b>``。"""
    items = list(constraints)
    if not items:
        return ''
    if len(items) == 1:
        return items[0].canonical()
    return '<' + ', '.join(c.canonical() for c in items) + '>'


# ═══════════════════════════════════════════════════════════
# 节点
# ═══════════════════════════════════════════════════════════
@dataclass
class AstNode:
    """AST 节点基类。"""

    source: SourceRange

    def children(self) -> Iterable['AstNode']:
        """直接子节点（供 :func:`walk` 遍历复用）。

        组合节点覆盖此方法返回直接子节点；叶子节点继承默认空实现。
        新增组合节点类型时必须实现，避免遍历逻辑与节点定义漂移。
        """
        return ()

    def canonical(self) -> str:
        """AST 规范化序列化：输出**标准 infd 源码**（无注释/空白，字段有序）。

        输出可被 :func:`~infinity_data.frontend.parse_source` 解析回等价 AST——
        round-trip 用于模板真名哈希（§2.5）、反序列化、调试与测试断言。
        新增节点类型时必须实现，避免序列化逻辑与节点定义漂移。
        """
        raise NotImplementedError(type(self).__name__)


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

    def children(self) -> Iterable[AstNode]:
        return self.statements

    def canonical(self) -> str:
        return '\n'.join(s.canonical() for s in self.statements)


# ═══════════════════════════════════════════════════════════
# 语句
# ═══════════════════════════════════════════════════════════


@dataclass
class TemplateImportItem(AstNode):
    """模板导入项: Name [as Alias]。"""

    name: str  # 被导入文件中的模板名
    alias: str | None = None  # 本地别名（可选）

    def canonical(self) -> str:
        if self.alias is None:
            return self.name
        return f'{self.name} as {self.alias}'


@dataclass
class TemplateImportStmt(AstNode):
    """模板导入: !from "path" import Name1, Name2 as N2"""

    from_path: str  # 文件路径（unix 风格）
    items: list[TemplateImportItem]  # 导入项列表

    def children(self) -> Iterable[AstNode]:
        return self.items

    def canonical(self) -> str:
        items = ', '.join(i.canonical() for i in self.items)
        return f'!from {_canonical_str(self.from_path)} import {items}'


@dataclass
class EnvImportStmt(AstNode):
    """环境变量导入: !env import NAME [as NEW_NAME]"""

    name: str  # 环境变量名
    alias: str | None  # 别名（可选）

    def canonical(self) -> str:
        if self.alias is None:
            return f'!env import {self.name}'
        return f'!env import {self.name} as {self.alias}'


@dataclass
class JsonPathKey(AstNode):
    """JSON 路径中的键访问: .key 或 .\"key\""""

    key: str

    def canonical(self) -> str:
        # 合法标识符（且非 as，规避 §4.4 首段 as 特殊规则）→ .key；否则 ."key"
        if self.key != 'as' and self.key.isidentifier():
            return '.' + self.key
        return '.' + _canonical_str(self.key)


@dataclass
class JsonPathIndex(AstNode):
    """JSON 路径中的索引访问: [N]"""

    index: int

    def canonical(self) -> str:
        return f'[{self.index}]'


type JsonPathSegment = JsonPathKey | JsonPathIndex


@dataclass
class FileImportItem(AstNode):
    """配置文件导入项。"""

    json_path: list[JsonPathSegment]  # 路径段列表；空列表 = 导入整个文件
    alias: str  # 别名（必须）

    def children(self) -> Iterable[AstNode]:
        return self.json_path

    def canonical(self) -> str:
        path = ''.join(s.canonical() for s in self.json_path) or '.'
        return f'{path} as {self.alias}'


@dataclass
class FileImportStmt(AstNode):
    """配置文件导入: !file "path" as <format> import .path.to.key as alias, ..."""

    file_path: str  # 文件路径
    format: str | None  # 文件格式: "yaml", "json", "toml" 或 None（自动检测后缀）
    imports: list[FileImportItem]

    def children(self) -> Iterable[AstNode]:
        return self.imports

    def canonical(self) -> str:
        fmt = f' as {self.format}' if self.format else ''
        items = ', '.join(i.canonical() for i in self.imports)
        return f'!file {_canonical_str(self.file_path)}{fmt} import {items}'


@dataclass
class VarStmt(AstNode):
    """本地注入: !var <值表达式> import [path] as <name>（§2.10）。

    值表达式求值后按 JSON path 投影，绑定到 ``$`` 空间（不进输出，仅被 ``$`` 引用消费）。
    """

    value: Value
    json_path: list[JsonPathSegment]  # 空列表 = 整值（仅 `.`）
    alias: str  # $ 空间别名

    def children(self) -> Iterable[AstNode]:
        return [self.value]

    def canonical(self) -> str:
        path = ''.join(s.canonical() for s in self.json_path) or '.'
        return f'!var {self.value.canonical()} import {path} as {self.alias}'


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

    def children(self) -> Iterable[AstNode]:
        return [self.constraints] + ([self.default_value] if self.default_value is not None else [])

    def canonical(self) -> str:
        head = f'{self.name}: {self.constraints.canonical()}'
        if self.default_value is not None:
            return f'{head} = {self.default_value.canonical()}'
        return head


@dataclass
class TemplateConfig:
    """模板头部配置（``~X(key=value)``），语法层解析为类型化字段。

        - ``allow_extra``：校验时是否放行额外字段（模板即约束 / schema）
        - ``positional``：是否允许位置参数（false = 只接受命名参数）
        - ``description``：模板文档（元数据，暂不消费，供 LSP/文档）
    ti ge    - ``extra_positional_vars``：多余位置参数收集到指定字段（list，§2.9）
        - ``extra_named_vars``：未声明命名参数收集到指定字段（dict，§2.9）

        未来新增配置项：在此加字段，parser 侧在对应键集合补一行（字段即白名单）。
    """

    allow_extra: bool = False
    positional: bool = True
    description: str | None = None
    extra_positional_vars: str | None = None
    extra_named_vars: str | None = None

    def canonical(self) -> str:
        parts: list[str] = []
        if self.allow_extra:
            parts.append('allow_extra = true')
        if not self.positional:
            parts.append('positional = false')
        if self.description is not None:
            parts.append(f'description = {_canonical_str(self.description)}')
        if self.extra_positional_vars is not None:
            parts.append(f'extra_positional_vars = {_canonical_str(self.extra_positional_vars)}')
        if self.extra_named_vars is not None:
            parts.append(f'extra_named_vars = {_canonical_str(self.extra_named_vars)}')
        if not parts:
            return ''
        return '(' + ', '.join(parts) + ')'


@dataclass
class TemplateDef(AstNode):
    """模板定义: ~Name { ... } 或 ~Name(config=value) { ... }"""

    name: str
    fields: list[TemplateField]
    config: TemplateConfig = field(default_factory=TemplateConfig)
    constraints: list[Constraint] = field(default_factory=lambda: [])

    def children(self) -> Iterable[AstNode]:
        return [*self.fields, *self.constraints]

    def canonical(self) -> str:
        inner: list[str] = [f.canonical() for f in self.fields]
        cs = _canonical_constraint_list(self.constraints)
        if cs:
            inner.append(': ' + cs)
        return f'~{self.name}{self.config.canonical()} {{ ' + ', '.join(inner) + ' }'


@dataclass
class Field(AstNode):
    """普通字段定义：name[: type] [= value]。

    值缺失（裸 key）不是合法语法：语义分析阶段报错。
    noexist 需显式书写 ``= noexist`` 字面量。
    """

    name: str
    constraints: Constraints | None = None
    value: Value | None = None

    def children(self) -> Iterable[AstNode]:
        out: list[AstNode] = []
        if self.value is not None:
            out.append(self.value)
        if self.constraints is not None:
            out.append(self.constraints)
        return out

    def canonical(self) -> str:
        cs = _canonical_constraint_list(self.constraints.constraints) if self.constraints is not None else ''
        head = f'{self.name}: {cs}' if cs else self.name
        if self.value is not None:
            return f'{head} = {self.value.canonical()}'
        return head


@dataclass
class ConstraintStmt(AstNode):
    """顶层结构级约束: ``: <constraint, ...>``（作用于编译产物 root）。

    顶层是隐式 dict，``:`` 起始的语句约束整个 root，而非某个字段。
    约束函数与字段级约束共用同一注册表。
    """

    constraints: list[Constraint]

    def children(self) -> Iterable[AstNode]:
        return self.constraints

    def canonical(self) -> str:
        return ': ' + _canonical_constraint_list(self.constraints)


# ═══════════════════════════════════════════════════════════
# 约束
# ═══════════════════════════════════════════════════════════


@dataclass
class ConstraintIdent(AstNode):
    """简单约束标识符，如 int, str, ?"""

    name: str

    def canonical(self) -> str:
        return self.name


@dataclass
class ConstraintCall(AstNode):
    """约束函数调用，如 each(str)、range(1, 10)、not(?)、any(int, str)。"""

    name: str
    arguments: list[Constraint] = field(default_factory=lambda: [])

    def children(self) -> Iterable[AstNode]:
        return self.arguments

    def canonical(self) -> str:
        args = ', '.join(a.canonical() for a in self.arguments)
        return f'{self.name}({args})'


@dataclass
class ConstraintLiteral(AstNode):
    """约束中的字面量参数，如 range(1, 10) 中的 1、10。"""

    value: LiteralValue

    def children(self) -> Iterable[AstNode]:
        return [self.value]

    def canonical(self) -> str:
        return self.value.canonical()


type Constraint = ConstraintIdent | ConstraintCall | ConstraintLiteral | ErrorConstraint


@dataclass
class Constraints(AstNode):
    """约束列表，如 int, str?, <int, range(1,10)>, <int, each(str)>。

    语义说明：
    - constraints 列表，若 len > 1，隐含 all(constraint1, constraint2, ...)
    """

    constraints: list[Constraint] = field(default_factory=lambda: [])

    def children(self) -> Iterable[AstNode]:
        return self.constraints

    def canonical(self) -> str:
        return _canonical_constraint_list(self.constraints)


# ═══════════════════════════════════════════════════════════
# 值
# ═══════════════════════════════════════════════════════════


@dataclass
class LiteralValue(AstNode):
    """字面量值"""

    value: FloatToken | IntegerToken | BoolToken | NullToken | NoexistToken | StringToken

    def canonical(self) -> str:
        return self.value.canonical()


@dataclass
class DollarValue(AstNode):
    """$ 导入空间引用: $NAME [as type]。

    用于引用 !env import 导入的变量。
    """

    name: str  # 变量名
    type_cast: Literal['int', 'float', 'bool', 'str', None]  # 可选类型转换

    def canonical(self) -> str:
        if self.type_cast is None:
            return f'${self.name}'
        return f'${self.name} as {self.type_cast}'


@dataclass
class UnpackValue(AstNode):
    """解包表达式：``*expr``（list 元素展开）或 ``**expr``（dict 键值展开）。

    出现在 dict 值 / list 元素 / 模板调用参数中，语义阶段展开进当前容器。
    """

    value: Value
    double: bool  # True = **（dict）；False = *（list）

    def children(self) -> Iterable[AstNode]:
        return [self.value]

    def canonical(self) -> str:
        return ('**' if self.double else '*') + self.value.canonical()


@dataclass
class DictValue(AstNode):
    """对象值: { ... }

    ``: <constraint, ...>`` 结构级约束作用于该字面量 dict 的整体。
    ``unpacks``：``**expr`` 解包项（展开为键值对后并入字段集）。
    """

    fields: list[Field]
    constraints: list[Constraint] = field(default_factory=lambda: [])
    unpacks: list[UnpackValue] = field(default_factory=lambda: [])

    def children(self) -> Iterable[AstNode]:
        return [*self.fields, *self.constraints, *self.unpacks]

    def canonical(self) -> str:
        inner: list[str] = [f.canonical() for f in self.fields]
        inner.extend(u.canonical() for u in self.unpacks)
        cs = _canonical_constraint_list(self.constraints)
        if cs:
            inner.append(': ' + cs)
        return '{ ' + ', '.join(inner) + ' }'


@dataclass
class ArrayValue(AstNode):
    """数组值: [ ... ]（元素可为 ``*expr`` 解包项，展开为元素）"""

    elements: list[Value | UnpackValue]

    def children(self) -> Iterable[AstNode]:
        return self.elements

    def canonical(self) -> str:
        return '[ ' + ', '.join(e.canonical() for e in self.elements) + ' ]'


@dataclass
class TemplateCallValue(AstNode):
    """模板调用: Name(args...)

    展开（§2.8）：参数值后缀 ``...`` = 展开轴；调用级（``)`` 后）``...`` = 笛卡尔积。
    - ``axis_positional``：位置参数中带 ``...`` 的索引
    - ``axis_named``：命名参数中带 ``...`` 的键
    - ``axis_unpack_kwargs``：``**expr`` 解包参数中带 ``...`` 的索引
    - ``cartesian``：调用级 ``...``（笛卡尔积；无 = zip）
    """

    template_name: str
    positional_args: list[Value]
    named_args: dict[str, Value]
    unpack_args: list[UnpackValue] = field(default_factory=lambda: [])  # *expr（list → 位置参数）
    unpack_kwargs: list[UnpackValue] = field(default_factory=lambda: [])  # **expr（dict → 命名参数）
    axis_positional: frozenset[int] = field(default_factory=frozenset[int])
    axis_named: frozenset[str] = field(default_factory=frozenset[str])
    axis_unpack_kwargs: frozenset[int] = field(default_factory=frozenset[int])
    cartesian: bool = False

    def children(self) -> Iterable[AstNode]:
        return [
            *self.positional_args,
            *self.named_args.values(),
            *self.unpack_args,
            *self.unpack_kwargs,
        ]

    def canonical(self) -> str:
        args: list[str] = []
        for i, a in enumerate(self.positional_args):
            s = a.canonical()
            if i in self.axis_positional:
                s += '...'
            args.append(s)
        args.extend(u.canonical() for u in self.unpack_args)
        for k, v in sorted(self.named_args.items()):
            s = f'{k} = {v.canonical()}'
            if k in self.axis_named:
                s += '...'
            args.append(s)
        for j, u in enumerate(self.unpack_kwargs):
            s = u.canonical()
            if j in self.axis_unpack_kwargs:
                s += '...'
            args.append(s)
        out = f'{self.template_name}({", ".join(args)})'
        if self.cartesian:
            out += '...'
        return out


# ═══════════════════════════════════════════════════════════
# 错误节点
# ═══════════════════════════════════════════════════════════


@dataclass
class ErrorStatement(AstNode):
    """解析失败的语句。用于错误恢复。"""

    message: str

    def canonical(self) -> str:
        raise TypeError('错误节点不可序列化为 infd')


@dataclass
class ErrorValue(AstNode):
    """解析失败的值。用于错误恢复。"""

    message: str

    def canonical(self) -> str:
        raise TypeError('错误节点不可序列化为 infd')


@dataclass
class ErrorConstraint(AstNode):
    """解析失败的约束。用于错误恢复。"""

    message: str

    def canonical(self) -> str:
        raise TypeError('错误节点不可序列化为 infd')


# ═══════════════════════════════════════════════════════════
# 联合类型
# ═══════════════════════════════════════════════════════════

type Statement = (
    TemplateImportStmt
    | EnvImportStmt
    | FileImportStmt
    | VarStmt
    | TemplateDef
    | Field
    | ConstraintStmt
    | UnpackValue  # 顶层（隐式 dict）**expr 解包
    | ErrorStatement
)
type Value = LiteralValue | DollarValue | DictValue | ArrayValue | TemplateCallValue | ErrorValue


# ═══════════════════════════════════════════════════════════
# 通用遍历
# ═══════════════════════════════════════════════════════════


def walk(node: AstNode) -> Iterator[AstNode]:
    """深度优先遍历 AST，产出所有节点（含自身）。

    基于各节点 :meth:`AstNode.children`——供依赖提取（模板真名）、默认值引用检测、
    诊断定位与未来 fmt 复用。新增组合节点类型时实现 ``children`` 即可。
    """
    yield node
    for child in node.children():
        yield from walk(child)
