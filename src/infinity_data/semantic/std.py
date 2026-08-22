"""标准 AST 值数据模型（中立数据层，Phase 1 / 2 共用）。

:mod:`std` 是中立数据层：不依赖 resolver / builder / executor 任何逻辑模块，
只依赖 infra（:class:`SourceRange`）与 typing。Phase 1（导入解析）与 Phase 2
（构建 / 执行）都消费本层——避免「Phase 1 依赖 Phase 2 数据模型」的反向耦合。

- 三态可空：``noexist``（键不存在）/ ``null``（键存在值为 null）/ value
- 浮点统一为 :class:`decimal.Decimal`（规范要求无限精度十进制浮点）
- ``python_to_std``：外部数据（dict / list / 标量）→ StdValue 树（统一入口）
- ``_STD_VALUE_TYPES``：StdValue 成员 tuple（``isinstance`` 用；新增成员只改此处）
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal, TypeGuard, cast

from infinity_data.infra.location import SourceRange

if TYPE_CHECKING:
    from infinity_data.semantic.resolver.models import TemplateKey

__all__ = [
    'LiteralKind',
    'ResolvedConstraint',
    'STD_VALUE_TYPES',
    'StdArray',
    'StdField',
    'StdLiteral',
    'StdObject',
    'StdValue',
    'is_std_value',
    'python_to_std',
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


def is_std_value(v: object) -> TypeGuard[StdValue]:
    """是否为 StdValue（:class:`StdLiteral` / :class:`StdArray` / :class:`StdObject`）。

    标注 :class:`TypeGuard` 以支持调用方类型收窄（如 `if is_std_value(x)` 后 x 为 StdValue）。
    """
    return isinstance(v, STD_VALUE_TYPES)


def python_to_std(value: Any) -> StdValue:
    """Python 值 → StdValue 树（外部导入数据统一入口，§2.7 / §3.3）。

    ``!file`` / ``!env`` 导入的原始数据经此转为 AST 后再消费（JSON path、约束、
    输出全部操作 StdValue）；``!var`` 的求值结果本就是 StdValue，无需此转换。
    """
    if value is None:
        return StdLiteral(kind='null', value=None)
    if isinstance(value, bool):
        return StdLiteral(kind='bool', value=value)
    if isinstance(value, int):
        return StdLiteral(kind='int', value=value)
    if isinstance(value, decimal.Decimal):
        return StdLiteral(kind='float', value=value)
    if isinstance(value, float):
        return StdLiteral(kind='float', value=decimal.Decimal(str(value)))
    if isinstance(value, str):
        return StdLiteral(kind='str', value=value)
    if isinstance(value, list):
        items = cast(list[Any], value)
        return StdArray(elements=[python_to_std(e) for e in items])
    if isinstance(value, dict):
        mapping = cast(dict[Any, Any], value)
        return StdObject(fields=[StdField(name=str(k), value=python_to_std(v)) for k, v in mapping.items()])
    return StdLiteral(kind='str', value=str(value))


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


STD_VALUE_TYPES: Final = (StdLiteral, StdArray, StdObject)
"""StdValue 成员 tuple：``isinstance`` 不能用于 union alias，此字面量常量供
``isinstance(x, STD_VALUE_TYPES)`` 使用（精确类型，pyright 可收窄）——
新增 StdValue 成员只改此处。"""
