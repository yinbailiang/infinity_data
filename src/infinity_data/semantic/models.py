"""语义分析阶段的标准 AST（StdAst）与统一诊断模型。

StdAst 是模板展开、约束解析之后的规范化 AST，**携带约束但不执行**：

- 三态可空：``noexist``（键不存在）/ ``null``（键存在值为 null）/ value
- 浮点统一为 :class:`decimal.Decimal`（规范要求无限精度十进制浮点）
- ``nan`` / ``+inf`` / ``-inf`` 以 ``Decimal("NaN")`` / ``Decimal("Infinity")`` /
  ``Decimal("-Infinity")`` 表示，kind 均为 ``"float"``
- 节点携带已解析约束（:class:`ResolvedConstraint`），由 :class:`ConstraintExecutor`
  遍历执行（只校验，不转换）
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass, field
from typing import Any, Literal

from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.infra.location import SourceRange
from infinity_data.parser.models import TemplateDef

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
    """标准文档：顶层对象 + 诊断信息 + 模板表与可见名表。

    - ``root``：编译产物（顶层对象）
    - ``diagnostics``：统一诊断
    - ``templates``：全部已加载模板（:class:`TemplateKey` → 定义，含 ``!from`` 导入的）
    - ``scope``：**入口文件**的可见名表（可见名 → :class:`TemplateKey`），
      与 ``templates`` 配合可完整解析：可见名 → TemplateKey → TemplateDef
    """

    root: StdObject = field(default_factory=StdObject)
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])
    templates: dict[TemplateKey, TemplateDef] = field(default_factory=lambda: {})
    scope: Scope = field(default_factory=lambda: {})

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.diagnostics)


# ═══════════════════════════════════════════════════════════
# 导入解析上下文（Phase 1 产物）
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ResolvedContext:
    """导入解析（Phase 1）产物：模板图 + 可见名表 + 数据命名空间。

    由 :class:`infinity_data.semantic.resolver.TemplateGraphResolver` 产出，
    供 :class:`infinity_data.semantic.analyzer.AstBuilder`（Phase 2a）消费。
    只含名字与模板定义，不含任何约束执行结果（约束求值属 Phase 2）。

    - ``templates``：全部已加载模板（本地 + ``!from`` 导入）
    - ``template_scopes``：每个模板定义点的可见名表（展开/校验按定义点可见性解析）
    - ``root_scope``：入口文件可见名表（可见名 → :class:`TemplateKey`）
    - ``schema_scope``：schema.from_file 隐式导入的可见名表（无则 None）
    - ``namespace``：``$`` 引用命名空间（``!env`` / ``!file`` 解析结果）
    - ``diagnostics``：Phase 1 诊断（``import.*`` / ``template.*`` 域）
    """

    templates: dict[TemplateKey, TemplateDef]
    template_scopes: dict[TemplateKey, Scope]
    root_scope: Scope
    schema_scope: Scope | None
    namespace: dict[str, Any]
    diagnostics: tuple[Diagnostic, ...]


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


Scope = dict[str, TemplateKey]
"""文件级可见名表：可见名 → 模板真名（:class:`TemplateKey`）。"""
