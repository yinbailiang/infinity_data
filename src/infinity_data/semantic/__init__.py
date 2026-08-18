"""语义分析：模板展开、约束执行、三态可空值模型。

导入 :mod:`infinity_data.semantic.diagnostics` 以注册本层全部诊断定义
（副作用，导入即注册进全局注册表）。
"""

from infinity_data.semantic import (
    diagnostics,
)
from infinity_data.semantic.analyzer import SemanticAnalyzer
from infinity_data.semantic.imports import ImportResolver
from infinity_data.semantic.models import (
    Diagnostic,
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
    ResolvedConstraint,
)

__all__ = [
    'SemanticAnalyzer',
    'ImportResolver',
    'ConstraintRegistry',
    'ConstraintResult',
    'ResolvedConstraint',
    'Diagnostic',
    'Severity',
    'StdArray',
    'StdDocument',
    'StdField',
    'StdLiteral',
    'StdObject',
    'StdValue',
    'diagnostics'
]
