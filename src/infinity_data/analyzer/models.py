"""StandardAst 模型 —— 语义分析后的完全展开、校验、无歧义的 AST。

基于 neo_desg.md 重新设计：
- 三态可空: noexist, null, value
- 新的字面量: nan, +inf, -inf
- object 作为通用超类型
- 模板即约束的展开结果
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infinity_data.tokenizer.models.raw_tokens import SourceInfo

# ═══════════════════════════════════════════════════════════
# 值
# ═══════════════════════════════════════════════════════════

@dataclass
class StdLiteral:
    """标准字面量值。

    kind 和 Python 值的对应:
    - "str"    → str
    - "mlstr"  → str (多行字符串)
    - "int"    → int
    - "float"  → float
    - "bool"   → bool
    - "null"   → None
    - "noexist"→ 不存在（键不出现在解析结果中）
    - "nan"    → float('nan')
    - "+inf"   → float('inf')
    - "-inf"   → float('-inf')
    - "object" → Any (通用超类型)
    """
    kind: str
    value: Any


@dataclass
class StdArray:
    """标准数组值。"""
    elements: list[StdValue] = field(default_factory=lambda: [])


@dataclass
class StdObject:
    """标准对象值。"""
    fields: list[StdField] = field(default_factory=lambda: [])


type StdValue = StdLiteral | StdObject | StdArray


# ═══════════════════════════════════════════════════════════
# 字段
# ═══════════════════════════════════════════════════════════

@dataclass
class StdField:
    """标准字段：名称 + 已校验的值 + 可选来源信息。"""
    name: str
    value: StdValue | None
    source: SourceInfo | None = None

    @property
    def is_noexist(self) -> bool:
        """是否为 noexist 标记（键不出现在结果中）。"""
        return isinstance(self.value, StdLiteral) and self.value.kind == "noexist"

    @property
    def is_null(self) -> bool:
        """值是否为 null。"""
        return isinstance(self.value, StdLiteral) and self.value.kind == "null"


# ═══════════════════════════════════════════════════════════
# 文档
# ═══════════════════════════════════════════════════════════

@dataclass
class StdDocument:
    """标准文档：顶层对象 + 可选的诊断信息。"""
    root: StdObject = field(default_factory=StdObject)
    diagnostics: list[Diagnostic] = field(default_factory=lambda: [])

    @property
    def has_errors(self) -> bool:
        return any(d.level == "error" for d in self.diagnostics)


# ═══════════════════════════════════════════════════════════
# 诊断
# ═══════════════════════════════════════════════════════════

@dataclass
class Diagnostic:
    """语义分析过程中的诊断信息。"""
    level: str  # "error" | "warning" | "info"
    message: str
    source: SourceInfo | None = None
    path: str = ""  # 字段路径，如 "MyApp.database.port"

