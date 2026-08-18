"""语义分析：AST 构建（Phase 2a）、约束执行（Phase 2b）、三态可空值模型。

导入 :mod:`infinity_data.semantic.diagnostics` 以注册本层全部诊断定义
（副作用，导入即注册进全局注册表）。
"""

from infinity_data.semantic import (
    diagnostics,
)
from infinity_data.semantic.analyzer import AstBuilder
from infinity_data.semantic.executor import ConstraintExecutor
from infinity_data.semantic.imports import ImportResolver
from infinity_data.semantic.models import (
    Diagnostic,
    ResolvedConstraint,
    ResolvedContext,
    Severity,
    StdArray,
    StdDocument,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.semantic.registry import (
    ConstraintRegistry,
    ConstraintResult,
)
from infinity_data.semantic.resolver import TemplateGraphResolver

__all__ = [
    'AstBuilder',
    'ConstraintExecutor',
    'ImportResolver',
    'TemplateGraphResolver',
    'ConstraintRegistry',
    'ConstraintResult',
    'ResolvedConstraint',
    'ResolvedContext',
    'Diagnostic',
    'Severity',
    'StdArray',
    'StdDocument',
    'StdField',
    'StdLiteral',
    'StdObject',
    'StdValue',
    'diagnostics',
]
