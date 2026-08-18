"""语义分析阶段的标准 AST（StdAst）与统一诊断模型。

StdAst 是模板展开、约束校验之后的规范化 AST：

- 三态可空：``noexist``（键不存在）/ ``null``（键存在值为 null）/ value
- 浮点统一为 :class:`decimal.Decimal`（规范要求无限精度十进制浮点）
- ``nan`` / ``+inf`` / ``-inf`` 以 ``Decimal("NaN")`` / ``Decimal("Infinity")`` /
  ``Decimal("-Infinity")`` 表示，kind 均为 ``"float"``
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field
from typing import Literal

from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.infra.location import SourceRange

LiteralKind = Literal['str', 'int', 'float', 'bool', 'null', 'noexist']
"""字面量 kind 枚举。"""


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
    """标准字段：名称 + 已校验的值 + 来源信息。"""

    name: str
    value: StdValue | None
    source: SourceRange | None = None

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
    """标准对象值。"""

    fields: list[StdField] = field(default_factory=list[StdField])

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
    """标准文档：顶层对象 + 诊断信息。"""

    root: StdObject = field(default_factory=StdObject)
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.diagnostics)


# ═══════════════════════════════════════════════════════════
# 模板身份
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TemplateKey:
    """模板唯一身份：来源文件内容 hash + 模板本地名。

    - ``content_hash``：来源文件内容的 sha256 前缀（机器无关，内容寻址）
    - ``name``：模板在来源文件中的本地名（诊断显示用）

    frozen 保证可哈希，直接作为 ``_templates`` 等表的键。
    """

    content_hash: str
    name: str

    def __str__(self) -> str:
        return f'{self.content_hash}:{self.name}'
