"""语义层：StdAst 数据模型与诊断类型（产物面）。

内部实现（导入解析 / AST 构建 / 约束执行）不在此重导出，
消费方按模块路径直接引用（pipeline / 测试）。

导入 :mod:`infinity_data.semantic.diagnostics` 以注册本层全部诊断定义
（副作用，导入即注册进全局注册表）。
"""

from infinity_data.semantic import (
    diagnostics,
)
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

__all__ = [
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
