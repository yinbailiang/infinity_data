"""语义分析：模板展开、约束执行、三态可空值模型。"""

from infinity_data.semantic.analyzer import SemanticAnalyzer
from infinity_data.semantic.converter import reduce_array, reduce_object, reduce_value
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
    'reduce_array',
    'reduce_object',
    'reduce_value',
]
