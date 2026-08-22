"""Phase 2a（构建）数据模型：标准文档。

本子模块**只定义数据**，不包含任何构建逻辑（构建器见 :mod:`builder`）。
Phase 2b（约束执行）通过本层模型消费构建产物——子模块间仅经数据模型依赖。

- :class:`StdDocument`：编译产物（顶层对象 + 模板表 + 可见名表）
- 值数据模型（:class:`StdValue` 家族 / :class:`ResolvedConstraint` /
  :func:`python_to_std`）已移至中立数据层 :mod:`infinity_data.semantic.std`
  （Phase 1 / 2 共用），本层 re-export 保持 ``from ...builder.models import StdValue`` 兼容。

模板真名 :class:`TemplateKey` 与可见名表 :class:`Scope` 属 Phase 1 数据模型
（:mod:`infinity_data.semantic.resolver.models`），本层仅消费。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from infinity_data.parser import TemplateDef
from infinity_data.semantic.std import (
    LiteralKind,
    ResolvedConstraint,
    StdArray,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
    is_std_value,
    python_to_std,
)

if TYPE_CHECKING:
    from infinity_data.semantic.resolver.models import Scope, TemplateKey

__all__ = [
    'LiteralKind',
    'ResolvedConstraint',
    'StdArray',
    'StdDocument',
    'StdField',
    'StdLiteral',
    'StdObject',
    'StdValue',
    'is_std_value',
    'python_to_std',
]


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
