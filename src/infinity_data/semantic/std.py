"""标准 AST 值数据模型（中立数据层，Phase 1 / 2 共用）。

:mod:`std` 是中立数据层：不依赖 resolver / builder / executor 任何逻辑模块，
只依赖 infra（:class:`SourceRange`）与 typing。Phase 1（导入解析）与 Phase 2
（构建 / 执行）都消费本层——避免「Phase 1 依赖 Phase 2 数据模型」的反向耦合。

- 三态可空：``noexist``（键不存在）/ ``null``（键存在值为 null）/ value
- 浮点统一为 :class:`decimal.Decimal`（规范要求无限精度十进制浮点）
- ``python_to_std``：外部数据（dict / list / 标量）→ StdValue 树（统一入口）
- ``_STD_VALUE_TYPES``：StdValue 成员 tuple（``isinstance`` 用；新增成员只改此处）

**分层原则（与 emit 层是不同语义）**：

- 本层（``python ↔ std``，:func:`python_to_std` / :func:`std_to_python`）是
  **忠实互转**，确保**语义最小丢失**——path → :class:`PurePosixPath`、float →
  :class:`decimal.Decimal`、noexist → :data:`NOEXIST` 哨兵，三态无损 round-trip。
- emit 层（:mod:`infinity_data.emit`）则**从 Python 出发**投影到其他数据格式
  （JSON / YAML / TOML），无需担心完整性——有损投影：path → 字符串、
  Decimal 特殊值编码、可选的 ``{"__type__": ...}`` 自描述标记。

**emit 不应被本层内部使用**；流水线内部的 Python 表示一律走本层的忠实转换。
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field
from pathlib import PurePath, PurePosixPath
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
    'StdNode',
    'StdObject',
    'StdValue',
    'is_std_node',
    'is_std_value',
    'Noexist',
    'NOEXIST',
    'StdPythonValue',
    'python_to_std',
    'std_to_python',
]

LiteralKind = Literal['str', 'int', 'float', 'bool', 'null', 'noexist', 'path']
"""字面量 kind 枚举（含 ``path``：语言内 POSIX 路径，值用 :class:`PurePosixPath` 承载）。"""


class Noexist:
    """``noexist`` 哨兵：Python 域的三态可空表示（§1.6）。

    用于表达**「键不存在」这一态**——与 ``None``（键存在但为 null）严格区分：

    - Python 侧构造：``{'a': NOEXIST}`` → 字段 a 为 noexist（键不出现）；
      ``{'a': None}`` → 字段 a 为 null（键出现、值为 null）
    - :func:`python_to_std` 识别它 → ``noexist`` 字面量（否则 Python 侧无法表达三态）
    - :func:`std_to_python` **默认保留**（转换层无损）；``keep_noexist=False`` 时丢弃

    **参考用途**：控制发射层（emit）——:class:`~infinity_data.emit.config.EmitConfig`
    的 ``keep_noexist`` 开启时，经 :func:`~infinity_data.emit.converter.to_json` 等
    输出为 ``{"__type__": "noexist"}`` 自描述标记。
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return 'NOEXIST'


NOEXIST = Noexist()
"""``noexist`` 哨兵单例：表达「键不存在」而非「键存在但为 null」（§1.6）。

与 ``None`` 严格区分（``NOEXIST is not None``）；见 :class:`Noexist`。
"""


# ═══════════════════════════════════════════════════════════
# Python 域表示（忠实互转的类型契约）
# ═══════════════════════════════════════════════════════════


type StdPythonValue = (
    None
    | bool
    | int
    | decimal.Decimal
    | PurePosixPath
    | str
    | Noexist
    | list[StdPythonValue]
    | dict[str, StdPythonValue]
)
"""Python 域忠实表示（§1.6 三态 + 各 kind 的专有类型）。

:func:`std_to_python` 的返回类型与 :func:`python_to_std` 的**成对输入签名**：

- ``float`` kind → :class:`decimal.Decimal`（无限精度，非 Python ``float``）
- ``path`` kind → :class:`PurePosixPath`（语言内 POSIX 形式）
- ``null`` → ``None``；``noexist`` → :data:`NOEXIST` 哨兵（**默认保留**，无损）
- 数组 / dict 递归（dict 键恒为 ``str``，§1.4）

签名是「无丢失 round-trip 的规范形式」契约；``python_to_std`` 运行时刻意宽容
（外部数据入口：``float`` / ``PurePath`` 便利输入、未知类型回退 ``str``）。
测试构造 StdPythonValue 请用
:func:`~infinity_data.emit.converter.restore_python`。
"""
# ═══════════════════════════════════════════════════════════
# 节点基类（统一携带来源位置）
# ═══════════════════════════════════════════════════════════


@dataclass
class StdNode:
    """标准 AST 节点基类：整棵 std 树（值 / 字段 / 约束）统一携带来源位置。

    - ``source``：节点在源文档中的位置（约束失败诊断指向被检查的对象本身）；
      ``!file`` / ``!env`` / ``!var`` 导入等合成值无来源时为 None
    - ``source`` 为 **keyword-only** 且 ``compare=False``：不改变子类既有
      位置/关键字构造签名（``StdLiteral('int', 3)`` 照常可用），dataclass
      相等比较忽略位置
    """

    source: SourceRange | None = field(default=None, compare=False, kw_only=True)


# ═══════════════════════════════════════════════════════════
# 已解析约束
# ═══════════════════════════════════════════════════════════


@dataclass
class ResolvedConstraint(StdNode):
    """已解析的约束（挂在 StdAst 节点上，由执行器消费）。

    - ``name``：约束真名（模板名已经 scope 翻译）
    - ``args``：参数（字面量 → Python 值；嵌套约束 → :class:`ResolvedConstraint`）
    - ``source``：约束表达式来源（继承自 :class:`StdNode`，诊断寻址）
    """

    name: str
    args: list[Any] = field(default_factory=list[Any])


# ═══════════════════════════════════════════════════════════
# 值
# ═══════════════════════════════════════════════════════════


@dataclass
class StdLiteral(StdNode):
    """标准字面量值。

    kind 与 Python 值的对应：
    - ``"str"``    → str
    - ``"int"``    → int
    - ``"float"``  → Decimal（含 NaN / ±Infinity）
    - ``"bool"``   → bool
    - ``"null"``   → None
    - ``"noexist"``→ None（键不出现在结果中）
    - ``source``：字面量在源文档中的位置（继承自 :class:`StdNode`）
    """

    kind: LiteralKind
    value: str | int | decimal.Decimal | bool | PurePosixPath | None


type StdValue = StdLiteral | StdArray | StdObject


def is_std_value(v: object) -> TypeGuard[StdValue]:
    """是否为 StdValue（:class:`StdLiteral` / :class:`StdArray` / :class:`StdObject`）。

    标注 :class:`TypeGuard` 以支持调用方类型收窄（如 `if is_std_value(x)` 后 x 为 StdValue）。
    """
    return isinstance(v, STD_VALUE_TYPES)


def is_std_node(v: object) -> TypeGuard[StdNode]:
    """是否为 std 树节点（值 / 字段 / 约束，统一携带 ``source``）。

    用于需要「节点都带位置」的泛化处理（如诊断定位的逐级回退）。
    """
    return isinstance(v, StdNode)


def python_to_std(value: StdPythonValue) -> StdValue:
    """Python 值 → StdValue 树（外部导入数据统一入口，§2.7 / §3.3）。

    **成对签名**：与 :func:`std_to_python` 构成互逆对——
    ``StdPythonValue → StdValue`` / ``StdValue → StdPythonValue``。

    ``!file`` / ``!env`` 导入的原始数据经此转为 AST 后再消费（JSON path、约束、
    输出全部操作 StdValue）；``!var`` 的求值结果本就是 StdValue，无需此转换。

    ``noexist`` 语义经 :data:`NOEXIST` 哨兵表达（Python 侧无原生三态）：
    ``{'a': NOEXIST}`` → 字段 a 为 noexist；``{'a': None}`` → 字段 a 为 null。

    **签名是契约，运行时刻意宽容**：这是外部数据（json/yaml/toml）统一入口——
    ``float`` / ``PurePath`` 便利输入、未知类型回退 ``str`` 仍被接受并归一化；
    无丢失 round-trip 的**规范形式**见 :data:`StdPythonValue`
    （测试构造请用 :func:`~infinity_data.emit.converter.restore_python`）。
    """
    if value is NOEXIST:
        return StdLiteral(kind='noexist', value=None)
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
    if isinstance(value, PurePath):
        # 任意 pathlib 路径 → path 值（统一归一为语言内 POSIX 形式，§1.5）
        return StdLiteral(kind='path', value=PurePosixPath(value.as_posix()))
    if isinstance(value, str):
        return StdLiteral(kind='str', value=value)
    if isinstance(value, list):
        items = cast(list[Any], value)
        return StdArray(elements=[python_to_std(e) for e in items])
    if isinstance(value, dict):
        mapping = cast(dict[Any, Any], value)
        return StdObject(fields=[StdField(name=str(k), value=python_to_std(v)) for k, v in mapping.items()])
    return StdLiteral(kind='str', value=str(value))


def std_to_python(val: StdValue, *, keep_null: bool = True, keep_noexist: bool = True) -> StdPythonValue:
    """StdValue → Python 值（:func:`python_to_std` 的**忠实逆**，默认无损）。

    与 emit 的有损投影不同，本函数保真：
    - ``path`` → :class:`PurePosixPath`（保持路径语义，可 round-trip 回 std）
    - ``float`` → :class:`decimal.Decimal`（无限精度，round-trip 无损）
    - 三态可空：``noexist`` **默认保留**为 :data:`NOEXIST` 哨兵（转换层无损，§1.6）；
      ``keep_noexist=False`` 时丢弃（键不出现，输出投影语义）；``null`` 保留键
      （值为 None），``keep_null=False`` 时跳过

    返回类型 :data:`StdPythonValue` 是 Python 域忠实表示的规范形式。
    输出投影（键不出现、有损编码）见 emit 层与 :meth:`CompilationResult.value`。
    """
    match val:
        case StdLiteral():
            if val.kind == 'noexist':
                return NOEXIST if keep_noexist else None
            if val.kind == 'null':
                return None
            return val.value
        case StdArray():
            return [std_to_python(e, keep_null=keep_null, keep_noexist=keep_noexist) for e in val.elements]
        case StdObject():
            result: dict[str, Any] = {}
            for f in val.fields:
                if f.value is None:
                    continue
                if f.is_noexist:
                    if keep_noexist:
                        result[f.name] = NOEXIST
                    continue
                if f.is_null:
                    if keep_null:
                        result[f.name] = None
                    continue
                result[f.name] = std_to_python(f.value, keep_null=keep_null, keep_noexist=keep_noexist)
            return result
    raise TypeError(f'未知 StdValue 类型: {type(val)}')


@dataclass
class StdField(StdNode):
    """标准字段：名称 + 值 + 来源信息 + 注解约束。

    ``constraints``：字段注解约束（``key: <c> = v``），已解析未执行；
    ``source`` 继承自 :class:`StdNode`（字段在源文档中的位置）。
    """

    name: str
    value: StdValue | None
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
class StdArray(StdNode):
    """标准数组值（``source`` 继承自 :class:`StdNode`）。"""

    elements: list[StdValue] = field(default_factory=lambda: [])


@dataclass
class StdObject(StdNode):
    """标准对象值。

    - ``fields``：字段列表
    - ``template``：可选的来源模板（:class:`TemplateKey`）。模板展开的实例，
      或经「模板即约束」校验的手写 dict 会携带；None = 无关联模板（纯字面量）
    - ``constraints``：结构级约束（``: <...>`` 作用于整个 dict，含模板级约束），
      已解析未执行
    - ``source``：对象在源文档中的位置（继承自 :class:`StdNode`）
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
