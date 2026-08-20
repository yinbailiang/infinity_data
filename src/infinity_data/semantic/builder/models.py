"""Phase 2a（构建）数据模型：标准 AST（StdAst）与已解析约束。

本子模块**只定义数据**，不包含任何构建逻辑（构建器见 :mod:`builder`）。
Phase 2b（约束执行）通过本层模型消费构建产物——子模块间仅经数据模型依赖。

- 三态可空：``noexist``（键不存在）/ ``null``（键存在值为 null）/ value
- 浮点统一为 :class:`decimal.Decimal`（规范要求无限精度十进制浮点）
- ``nan`` / ``+inf`` / ``-inf`` 以 ``Decimal("NaN")`` / ``Decimal("Infinity")`` /
  ``Decimal("-Infinity")`` 表示，kind 均为 ``"float"``
- 节点携带已解析约束（:class:`ResolvedConstraint`），由 Phase 2b 遍历执行
  （只校验，不转换）

模板真名 :class:`TemplateKey` 与可见名表 :class:`Scope` 属 Phase 1 数据模型
（:mod:`infinity_data.semantic.resolver.models`），本层仅消费。
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from infinity_data.infra.location import SourceRange
from infinity_data.parser import TemplateDef

if TYPE_CHECKING:
    # 仅类型注解使用（from __future__ import annotations 下为惰性字符串）：
    # 运行时导入会经 resolver/__init__ → resolver.resolver → registry → builder.models
    # 形成循环（emit.converter 引导导入期间）。注解不发散，TYPE_CHECKING 即可。
    from infinity_data.semantic.resolver.models import Scope, TemplateKey

__all__ = [
    'ResolvedConstraint',
    'StdArray',
    'StdDocument',
    'StdField',
    'StdLiteral',
    'StdObject',
    'StdValue',
]

LiteralKind = Literal['str', 'int', 'float', 'bool', 'null', 'noexist']
"""字面量 kind 枚举。"""


# ═══════════════════════════════════════════════════════════
# 已解析约束
# ═══════════════════════════════════════════════════════════


@dataclass
class ResolvedConstraint:
    """已解析的约束（挂在 StdAst 节点上，由执行器消费）。

    - ``name``：约束真名（模板名已经 scope 翻译）
    - ``args``：参数（字面量 → Python 值；嵌套约束 → :class:`ResolvedConstraint`）
    - ``source``：约束表达式来源（诊断寻址）
    """

    name: str
    args: list[Any] = field(default_factory=list[Any])
    source: SourceRange | None = None


# ═══════════════════════════════════════════════════════════
# 值
# ═══════════════════════════════════════════════════════════


@dataclass
class StdLiteral:
    """标准字面量值。

    kind 与 Python 值的对应：
    - ``"str"``    → str
    - ``"int"``    → int
    - ``"float"``  → Decimal（含 NaN / ±Infinity）
    - ``"bool"``   → bool
    - ``"null"``   → None
    - ``"noexist"``→ None（键不出现在结果中）
    """

    kind: LiteralKind
    value: str | int | decimal.Decimal | bool | None


type StdValue = StdLiteral | StdArray | StdObject


@dataclass
class StdField:
    """标准字段：名称 + 值 + 来源信息 + 注解约束。

    ``constraints``：字段注解约束（``key: <c> = v``），已解析未执行。
    """

    name: str
    value: StdValue | None
    source: SourceRange | None = None
    constraints: list[ResolvedConstraint] = field(default_factory=list[ResolvedConstraint])

    @property
    def is_noexist(self) -> bool:
        """是否为 noexist 标记（键不出现在结果中）。"""
        return isinstance(self.value, StdLiteral) and self.value.kind == 'noexist'

    @property
    def is_null(self) -> bool:
        """值是否为 null。"""
        return isinstance(self.value, StdLiteral) and self.value.kind == 'null'


@dataclass
class StdArray:
    """标准数组值。"""

    elements: list[StdValue] = field(default_factory=list[StdValue])


@dataclass
class StdObject:
    """标准对象值。

    - ``fields``：字段列表
    - ``template``：可选的来源模板（:class:`TemplateKey`）。模板展开的实例，
      或经「模板即约束」校验的手写 dict 会携带；None = 无关联模板（纯字面量）
    - ``constraints``：结构级约束（``: <...>`` 作用于整个 dict，含模板级约束），
      已解析未执行
    """

    fields: list[StdField] = field(default_factory=list[StdField])
    template: TemplateKey | None = None
    constraints: list[ResolvedConstraint] = field(default_factory=list[ResolvedConstraint])

    def get(self, name: str) -> StdField | None:
        """按名称查找字段（无则 None）。"""
        for f in self.fields:
            if f.name == name:
                return f
        return None


# ═══════════════════════════════════════════════════════════
# 文档
# ═══════════════════════════════════════════════════════════


@dataclass
class StdDocument:
    """标准文档（**纯数据**）：顶层对象 + 模板表与可见名表。

    - ``root``：编译产物（顶层对象）
    - ``templates``：全部已加载模板（:class:`TemplateKey` → 定义，含 ``!from`` 导入的）
    - ``scope``：**入口文件**的可见名表（可见名 → :class:`TemplateKey`），
      与 ``templates`` 配合可完整解析：可见名 → TemplateKey → TemplateDef

    不携带诊断：所有诊断经共享 :class:`DiagnosticCollector` 收集，
    由流水线在 :class:`CompilationResult` 上承载——诊断不属于文档数据。
    """

    root: StdObject = field(default_factory=StdObject)
    templates: dict[TemplateKey, TemplateDef] = field(default_factory=lambda: {})
    scope: Scope = field(default_factory=lambda: {})
